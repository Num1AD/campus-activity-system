"""
routers/registrations.py —— 报名模块接口

接口（V1.0 已有，路径不变）：
- POST   /api/activities/{id}/register        学生报名
- DELETE /api/activities/{id}/register        学生取消报名 / 退出候补
- GET    /api/my-activities                   我的活动（学生=已报名；教师=我发布的）
- GET    /api/activities/{id}/registrations   教师查看某活动的报名名单

V2.0 新增接口：
- POST   /api/activities/{id}/registrations/{student_id}/review   教师审核报名（R-06、R-07）

V2.0 变化（对应报告第七章、第八章，需求编号 R-01~R-07）：
- 满员不再直接拒绝：名额已满时进入候补队列，记录 status=waitlisted 与 queued_at（R-01）
- 需审核的活动：报名先进入 status=pending，由组织教师审核后再定正式或候补（R-06、R-07）
- 取消报名按状态分支：正式参加取消后触发递补，队首候补转正式（R-04）
- 候补退出后依次前移，正式参加人数不变（R-05）

约束落实（第八章"关键状态或规则处理说明"）：
- 规则 1 名额口径：正式参加人数只统计 confirmed，候补与待审核不占用名额
- 规则 2 递补触发：取消与递补放在同一事务内完成，避免并发下漏补或多补
- 规则 3 队列顺序：候补按 queued_at 升序排列，作为递补的唯一依据
- 规则 4 判断顺序：先确认资格（审核），再看剩余名额，两个判断不合并
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import get_current_user
from backend.database import get_db
from backend.helpers import (
    EVT_APPLY,
    EVT_PROMOTED,
    EVT_REASON_TEXT,
    EVT_REVIEW_APPROVED,
    EVT_REVIEW_REJECTED,
    EVT_REVIEW_WAITLISTED,
    EVT_WITHDRAW,
    REG_CONFIRMED,
    REG_PENDING,
    REG_WAITLISTED,
    STATUS_REMOVED,
    activity_to_dict,
    calc_status,
    count_registrations,
    now_str,
    record_registration_event,
    reg_status_text,
)

router = APIRouter(prefix="/api", tags=["报名"])


def _load_activity(db: sqlite3.Connection, activity_id: int) -> sqlite3.Row:
    """按 id 取活动，不存在则 404。"""
    act = db.execute(
        "SELECT * FROM activities WHERE id = ?", (activity_id,)
    ).fetchone()
    if act is None:
        raise HTTPException(status_code=404, detail="活动不存在")
    return act


def _first_waitlisted(db: sqlite3.Connection, activity_id: int) -> sqlite3.Row | None:
    """
    取候补队列最靠前的一条记录。

    排序依据是 queued_at（进入候补的时间），与 R-02 一致；
    id 作为次级排序，保证同一时刻进入的候补也有稳定顺序。
    """
    return db.execute(
        "SELECT * FROM registrations WHERE activity_id = ? AND status = ? "
        "ORDER BY queued_at, id LIMIT 1",
        (activity_id, REG_WAITLISTED),
    ).fetchone()


def _queue_position(db: sqlite3.Connection, activity_id: int, user_id: int) -> int | None:
    """
    某学生在其候补队列中的位置（1 起），非候补返回 None。

    排序口径与递补规则完全一致（queued_at 升序，id 兜底），
    保证"显示的排队位置"与"实际被递补的先后"是同一套顺序（R3-01）。
    """
    rows = db.execute(
        "SELECT user_id FROM registrations WHERE activity_id = ? AND status = ? "
        "ORDER BY queued_at, id",
        (activity_id, REG_WAITLISTED),
    ).fetchall()
    for i, r in enumerate(rows, 1):
        if r["user_id"] == user_id:
            return i
    return None


def _queue_total(db: sqlite3.Connection, activity_id: int) -> int:
    """候补队列总人数（与排队位置同一口径）。"""
    return count_registrations(db, activity_id, REG_WAITLISTED)


# ---------------------------------------------------------------
# 学生报名 / 取消
# ---------------------------------------------------------------
@router.post("/activities/{activity_id}/register", summary="学生报名活动")
def register_activity(
    activity_id: int,
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """
    学生报名。按活动规则确定报名状态：
    - 需审核的活动 → 待审核，先确认资格（R-06）
    - 无需审核且有名额 → 正式参加
    - 无需审核但名额已满 → 候补中，并记录进入候补的时间（R-01）

    校验顺序（第八章规则 4）：活动状态 → 是否重复报名 → 是否需审核 → 剩余名额。
    """
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="仅学生可报名活动")

    act = _load_activity(db, activity_id)

    # 状态校验：已取消 / 已截止的活动不能报名
    status = calc_status(act["start_time"], act["is_cancelled"])
    if status != "报名中":
        raise HTTPException(status_code=400, detail=f"活动当前状态为「{status}」，无法报名")

    # BEGIN IMMEDIATE：立刻取写锁，避免"先读后写"时两个请求同时读到未满再相继写入
    try:
        db.execute("BEGIN IMMEDIATE")
        dup = db.execute(
            "SELECT id, status FROM registrations WHERE activity_id = ? AND user_id = ?",
            (activity_id, user["id"]),
        ).fetchone()
        if dup:
            # V3.0（R3-02）：重复报名不是"请求出错"，而是与当前状态冲突。
            # 返回 409 并带上当前状态，前端据此提示"你已报名，当前状态：正式参加"，
            # 而不是把一句"不能重复报名"当作错误弹出来——那正是数据里 126 条
            # 重复提交的成因：用户不确定第一次是否成功，又点了一次，结果看到报错。
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "你已报名该活动，无需重复提交",
                    "current_status": reg_status_text(dup["status"]),
                },
            )

        # R-06：需审核的活动先进入待审核，此时不占用名额
        if act["require_review"]:
            db.execute(
                "INSERT INTO registrations (activity_id, user_id, status) VALUES (?, ?, ?)",
                (activity_id, user["id"], REG_PENDING),
            )
            record_registration_event(
                db, activity_id, user["id"], None, REG_PENDING, EVT_APPLY
            )
            db.commit()
            return {
                "message": "报名已提交，等待组织教师审核",
                "activity_id": activity_id,
                "reg_status": reg_status_text(REG_PENDING),
            }

        # R-01 / R-07：无需审核时看剩余名额，满员进入候补而不是拒绝
        confirmed = count_registrations(db, activity_id, REG_CONFIRMED)
        if confirmed < act["capacity"]:
            db.execute(
                "INSERT INTO registrations (activity_id, user_id, status) VALUES (?, ?, ?)",
                (activity_id, user["id"], REG_CONFIRMED),
            )
            record_registration_event(
                db, activity_id, user["id"], None, REG_CONFIRMED, EVT_APPLY
            )
            db.commit()
            return {
                "message": "报名成功",
                "activity_id": activity_id,
                "reg_status": reg_status_text(REG_CONFIRMED),
            }

        queued_at = now_str()
        db.execute(
            "INSERT INTO registrations (activity_id, user_id, status, queued_at) "
            "VALUES (?, ?, ?, ?)",
            (activity_id, user["id"], REG_WAITLISTED, queued_at),
        )
        record_registration_event(
            db, activity_id, user["id"], None, REG_WAITLISTED, EVT_APPLY
        )
        db.commit()
        return {
            "message": "活动名额已满，已进入候补队列",
            "activity_id": activity_id,
            "reg_status": reg_status_text(REG_WAITLISTED),
            "queued_at": queued_at,
            "queue_position": _queue_position(db, activity_id, user["id"]),
        }
    except HTTPException:
        db.rollback()
        raise
    except sqlite3.IntegrityError:
        # UNIQUE 约束兜底（极端并发下重复报名）
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "message": "你已报名该活动，无需重复提交",
                "current_status": None,
            },
        )


@router.delete("/activities/{activity_id}/register", summary="学生取消报名或退出候补")
def unregister_activity(
    activity_id: int,
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """
    取消报名 / 退出候补，按当前状态分支处理：
    - 正式参加取消：释放一个位置，若存在候补则由队列最靠前者递补（R-04，同一事务内完成）
    - 候补中退出：删除记录，排在其后的人依次前移（R-05，顺序由 queued_at 决定）
    - 待审核撤回：删除记录
    """
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="仅学生可取消报名")

    _load_activity(db, activity_id)

    try:
        db.execute("BEGIN IMMEDIATE")
        reg = db.execute(
            "SELECT * FROM registrations WHERE activity_id = ? AND user_id = ?",
            (activity_id, user["id"]),
        ).fetchone()
        if reg is None:
            raise HTTPException(status_code=400, detail="你尚未报名该活动")

        db.execute("DELETE FROM registrations WHERE id = ?", (reg["id"],))
        # V3.0：本人主动取消/撤回，记一条事件（不提醒自己）
        record_registration_event(
            db, activity_id, user["id"], reg["status"], STATUS_REMOVED, EVT_WITHDRAW
        )

        promoted = None
        if reg["status"] == REG_CONFIRMED:
            # R-04：正式名额空出后优先给候补顺序最靠前的人
            nxt = _first_waitlisted(db, activity_id)
            if nxt is not None:
                db.execute(
                    "UPDATE registrations SET status = ?, queued_at = NULL WHERE id = ?",
                    (REG_CONFIRMED, nxt["id"]),
                )
                # V3.0：递补由系统触发，被递补的学生需要收到提醒（needs_notice=1）
                record_registration_event(
                    db, activity_id, nxt["user_id"],
                    REG_WAITLISTED, REG_CONFIRMED, EVT_PROMOTED,
                )
                promoted = nxt["user_id"]
        db.commit()
    except HTTPException:
        db.rollback()
        raise

    if reg["status"] == REG_WAITLISTED:
        return {"message": "已退出候补", "promoted_user_id": None}
    if reg["status"] == REG_PENDING:
        return {"message": "已撤回报名申请", "promoted_user_id": None}
    return {
        "message": "已取消报名" + ("，空出的名额已由候补最靠前的学生递补" if promoted else ""),
        "promoted_user_id": promoted,
    }


# ---------------------------------------------------------------
# 我的活动（按角色）
# ---------------------------------------------------------------
@router.get("/my-activities", summary="我的活动")
def my_activities(
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """按角色返回：
    - 学生：我报名过的活动列表，附带本人的报名状态（R-03）
    - 教师：我发布的活动列表（附带正式人数、候补人数、待审核人数）
    - 管理员：不参与活动业务，返回空列表（R-08）
    """
    if user["role"] == "student":
        rows = db.execute(
            "SELECT a.*, r.status AS reg_status, r.queued_at AS reg_queued_at "
            "FROM activities a JOIN registrations r ON r.activity_id = a.id "
            "WHERE r.user_id = ? ORDER BY a.start_time",
            (user["id"],),
        ).fetchall()
        result = []
        for r in rows:
            item = activity_to_dict(db, r)
            # 本人的报名状态（区别于活动状态，两者口径不同，见第八章规则说明）
            item["reg_status"] = reg_status_text(r["reg_status"])
            item["reg_status_code"] = r["reg_status"]
            item["reg_queued_at"] = r["reg_queued_at"]
            # V3.0（R3-01）：候补中时给出排队位置与队列总人数，
            # 让"还要等多久"从不可知变成至少知道前面有几个人
            if r["reg_status"] == REG_WAITLISTED:
                item["queue_position"] = _queue_position(db, r["id"], user["id"])
                item["waitlist_total"] = _queue_total(db, r["id"])
            else:
                item["queue_position"] = None
                item["waitlist_total"] = None
            result.append(item)
        return {"activities": result}

    if user["role"] == "teacher":
        # 排序与活动广场保持一致（按开始时间升序），否则教师切换两个视图时
        # 同一批活动顺序不同，看起来混乱
        rows = db.execute(
            "SELECT * FROM activities WHERE creator_id = ? ORDER BY start_time",
            (user["id"],),
        ).fetchall()
        return {"activities": [activity_to_dict(db, r) for r in rows]}

    # 管理员：不介入具体活动组织与报名业务
    return {"activities": []}


# ---------------------------------------------------------------
# 教师审核报名（V2.0 新增，R-06 / R-07）
# ---------------------------------------------------------------
class ReviewRequest(BaseModel):
    """审核报名请求体。"""
    approve: bool = Field(description="true=通过，false=拒绝")


@router.post(
    "/activities/{activity_id}/registrations/{student_id}/review",
    summary="教师审核报名",
)
def review_registration(
    activity_id: int,
    student_id: int,
    req: ReviewRequest,
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """
    审核本人活动收到的报名申请（R-06 / R-07）。

    判定顺序（第八章规则 4：先确认资格，再看剩余名额）：
    1. 通过审核后才进入名额判定，未通过的直接不能参加；
    2. 有名额 → 正式参加；名额已满 → 进入候补队列，此时才记录 queued_at。

    权限：只有该活动的发布教师可以审核，其他教师与学生均不可（R-06）。
    """
    if user["role"] != "teacher":
        raise HTTPException(status_code=403, detail="仅教师可审核报名")

    act = _load_activity(db, activity_id)
    if act["creator_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="只能审核自己发布活动的报名")

    try:
        db.execute("BEGIN IMMEDIATE")
        reg = db.execute(
            "SELECT * FROM registrations WHERE activity_id = ? AND user_id = ?",
            (activity_id, student_id),
        ).fetchone()
        if reg is None:
            raise HTTPException(status_code=404, detail="该学生未报名此活动")

        if reg["status"] != REG_PENDING:
            raise HTTPException(
                status_code=400,
                detail=f"该报名当前状态为「{reg_status_text(reg['status'])}」，只有待审核的报名可以审核",
            )

        # 未通过：报名记录移除，该学生不能参加（US-06 异常情形）
        if not req.approve:
            db.execute("DELETE FROM registrations WHERE id = ?", (reg["id"],))
            # V3.0：审核结果由教师触发，需要提醒学生（R3-01）
            record_registration_event(
                db, activity_id, student_id, REG_PENDING, STATUS_REMOVED, EVT_REVIEW_REJECTED
            )
            db.commit()
            return {
                "message": "已拒绝该报名申请",
                "result": "rejected",
                "reg_status": None,
            }

        # 通过：再看当时的剩余名额，两名额情形结果不同（R-07）
        confirmed = count_registrations(db, activity_id, REG_CONFIRMED)
        if confirmed < act["capacity"]:
            db.execute(
                "UPDATE registrations SET status = ? WHERE id = ?",
                (REG_CONFIRMED, reg["id"]),
            )
            record_registration_event(
                db, activity_id, student_id, REG_PENDING, REG_CONFIRMED, EVT_REVIEW_APPROVED
            )
            db.commit()
            return {
                "message": "审核通过，该学生已确定为正式参加",
                "result": "approved",
                "reg_status": reg_status_text(REG_CONFIRMED),
            }

        # 名额已满：审核通过也要进入候补，入队时间从此刻起算（R-02 的排序依据）
        queued_at = now_str()
        db.execute(
            "UPDATE registrations SET status = ?, queued_at = ? WHERE id = ?",
            (REG_WAITLISTED, queued_at, reg["id"]),
        )
        record_registration_event(
            db, activity_id, student_id, REG_PENDING, REG_WAITLISTED, EVT_REVIEW_WAITLISTED
        )
        db.commit()
        return {
            "message": "审核通过，但名额已满，该学生进入候补队列",
            "result": "approved",
            "reg_status": reg_status_text(REG_WAITLISTED),
            "queued_at": queued_at,
        }
    except HTTPException:
        db.rollback()
        raise


# ---------------------------------------------------------------
# 教师与管理员查看报名名单
# ---------------------------------------------------------------
@router.get("/activities/{activity_id}/registrations", summary="查看活动报名名单")
def list_registrations(
    activity_id: int,
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """
    查看活动报名名单（REQ-04：教师掌握报名情况）：
    - 教师：仅能查看自己创建的活动；名单按待审核 / 正式参加 / 候补中分组排序（R-03）
    - 管理员：可查看平台全部活动的名单，用于监督；仅只读，审核与名额判定仍限组织教师
      （属第八章的设计约定，不是访谈直接得到的规则，故不在需求表中作为需求列出）
    - 学生：拒绝（学生查看自己的报名状态由 /api/my-activities 提供）
    """
    role = user["role"]
    if role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="仅教师和管理员可查看报名名单")

    act = _load_activity(db, activity_id)
    # 教师限本人发布的活动；管理员出于监督需要可查看全部活动，但仍只读
    if role == "teacher" and act["creator_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="只能查看自己发布的活动")

    rows = db.execute(
        "SELECT u.id, u.username, u.name, r.status, r.queued_at, r.created_at "
        "FROM registrations r JOIN users u ON u.id = r.user_id "
        "WHERE r.activity_id = ? "
        "ORDER BY CASE r.status "
        "           WHEN 'pending' THEN 0 WHEN 'confirmed' THEN 1 ELSE 2 END, "
        "         r.queued_at, r.created_at",
        (activity_id,),
    ).fetchall()

    students = []
    for r in rows:
        students.append({
            "id": r["id"],
            "username": r["username"],
            "name": r["name"],
            "reg_status": r["status"],                     # 英文标识，供前端逻辑判断
            "reg_status_text": reg_status_text(r["status"]),  # 中文，直接展示
            "queued_at": r["queued_at"],                   # 候补排序依据（仅候补有值）
            "created_at": r["created_at"],
        })

    return {
        "activity_id": activity_id,
        "capacity": act["capacity"],
        "confirmed_count": count_registrations(db, activity_id, REG_CONFIRMED),
        "waitlisted_count": count_registrations(db, activity_id, REG_WAITLISTED),
        "pending_count": count_registrations(db, activity_id, REG_PENDING),
        # 管理员为只读查看，前端据此不渲染审核操作（教师为 False）
        "readonly": role == "admin",
        "students": students,
    }


# ---------------------------------------------------------------
# 我的报名状态变化（V3.0 新增，R3-01）
# ---------------------------------------------------------------
def _event_status_text(from_status: str | None, to_status: str, reason: str) -> str:
    """
    把事件的前后状态转成时间线上好读的文案。

    to_status=removed 时状态本身没有展示意义（记录已删除），
    要看原因才能分辨是"自己取消"还是"审核未通过"。
    """
    if to_status == STATUS_REMOVED:
        return "报名未通过" if reason == EVT_REVIEW_REJECTED else "已取消报名"
    return reg_status_text(to_status)


@router.get("/my-registration-events", summary="我的报名状态变化")
def my_registration_events(
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """
    返回本人报名的全部状态变化事件（R3-01）。

    - 学生：返回自己的事件，按时间正序，便于呈现"报名 → 候补 → 递补"的完整过程
    - 其他角色：拒绝（教师看名单、管理员看账号，均不涉及此视图）

    未读数只统计 needs_notice=1 的事件，即由教师或系统触发、并非本人操作的那些。
    学生自己报名或取消不会产生提醒，否则提醒会被自己的动作淹掉。
    """
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="仅学生可查看本人的报名状态变化")

    seen_id_row = db.execute(
        "SELECT events_seen_id FROM users WHERE id = ?", (user["id"],)
    ).fetchone()
    seen_id = seen_id_row["events_seen_id"] or 0

    rows = db.execute(
        "SELECT e.*, a.title AS activity_title "
        "FROM registration_events e JOIN activities a ON a.id = e.activity_id "
        "WHERE e.user_id = ? ORDER BY e.created_at, e.id",
        (user["id"],),
    ).fetchall()

    events = []
    unread = 0
    last_seen_at = None
    for r in rows:
        # 未读判断用事件 id 做游标：时间只精确到秒，同一秒内的多条事件按时间比较会漏
        is_new = bool(r["needs_notice"]) and r["id"] > seen_id
        if is_new:
            unread += 1
        if r["id"] == seen_id:
            last_seen_at = r["created_at"]
        events.append({
            "id": r["id"],
            "activity_id": r["activity_id"],
            "activity_title": r["activity_title"],
            "from_status_text": reg_status_text(r["from_status"]) if r["from_status"] else "",
            "to_status_text": _event_status_text(r["from_status"], r["to_status"], r["reason"]),
            "reason_text": EVT_REASON_TEXT.get(r["reason"], r["reason"]),
            "needs_notice": bool(r["needs_notice"]),
            "is_new": is_new,
            "created_at": r["created_at"],
        })

    return {
        "events": events,
        "unread_count": unread,
        "last_seen_at": last_seen_at,
    }


class MarkReadRequest(BaseModel):
    """
    标记已读请求体（可选）。

    until = 客户端本次实际加载到的最大事件 id。带上它可以避免一个竞态：
    前端先 GET 事件列表、再 POST 标记已读；若两步之间恰好有教师完成审核，
    后端按 MAX(id) 推进会把那条用户还没看到的事件一并标成已读，提醒就丢了。
    """
    until: int | None = Field(default=None, description="客户端已加载到的最大事件 id")


@router.post("/my-registration-events/read", summary="标记状态变化已读")
def mark_registration_events_read(
    req: MarkReadRequest | None = None,
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """
    推进已读游标（R3-01）。

    游标只前进不后退，且推进上限由 until 限定：
    - 带 until：只推进到客户端**已经看到**的那条事件，之后新产生的事件仍算未读；
    - 不带 until：推进到当前最新事件（兼容旧调用与测试脚本）。

    返回的 unread_count 是推进之后的真实未读数，而不是恒为 0 ——
    若在客户端加载之后又来了新事件，这里会如实返回，前端据此又挂上徽标。
    """
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="仅学生可标记本人的报名状态变化")

    latest = db.execute(
        "SELECT MAX(id) AS m FROM registration_events WHERE user_id = ?", (user["id"],)
    ).fetchone()["m"] or 0

    target = latest
    if req is not None and req.until is not None:
        # 不允许越过客户端已见位置，防止把未看到的事件吞掉
        target = min(latest, max(0, req.until))

    seen = db.execute(
        "SELECT events_seen_id FROM users WHERE id = ?", (user["id"],)
    ).fetchone()["events_seen_id"] or 0
    new_seen = max(seen, target)          # 游标只前进不后退

    db.execute("UPDATE users SET events_seen_id = ? WHERE id = ?", (new_seen, user["id"]))
    db.commit()

    unread = db.execute(
        "SELECT COUNT(*) AS n FROM registration_events "
        "WHERE user_id = ? AND needs_notice = 1 AND id > ?",
        (user["id"], new_seen),
    ).fetchone()["n"]
    last = db.execute(
        "SELECT created_at FROM registration_events WHERE user_id = ? AND id = ?",
        (user["id"], new_seen),
    ).fetchone()

    return {
        "message": "已标记为已读",
        "last_seen_at": last["created_at"] if last else None,
        "unread_count": unread,
    }
