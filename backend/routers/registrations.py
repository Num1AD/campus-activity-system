"""
routers/registrations.py —— 报名模块接口（REQ-06 报名/取消、REQ-07 我的活动）

接口：
- POST   /api/activities/{id}/register        学生报名（REQ-06）
- DELETE /api/activities/{id}/register        学生取消报名（REQ-06）
- GET    /api/my-activities                   我的活动（学生=已报名；教师=我发布的+报名名单）
- GET    /api/activities/{id}/registrations   教师查看某活动的报名名单

约束落实（docs/04-软件设计.md 4.4 决策 2/6，对应 REQ-08）：
- 报名必须在"报名中"状态、名额未满、且未重复报名
- 数据库 UNIQUE(activity_id, user_id) 做最终兜底
- 名额检查与写入放在同一事务内，避免并发超员
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import get_current_user
from backend.database import get_db
from backend.helpers import activity_to_dict, calc_status, now_str

router = APIRouter(prefix="/api", tags=["报名"])


def _load_activity(db: sqlite3.Connection, activity_id: int) -> sqlite3.Row:
    """按 id 取活动，不存在则 404。"""
    act = db.execute(
        "SELECT * FROM activities WHERE id = ?", (activity_id,)
    ).fetchone()
    if act is None:
        raise HTTPException(status_code=404, detail="活动不存在")
    return act


def _count_registered(db: sqlite3.Connection, activity_id: int) -> int:
    """统计某活动当前报名人数。"""
    return db.execute(
        "SELECT COUNT(*) AS n FROM registrations WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()["n"]


# ---------------------------------------------------------------
# 学生报名 / 取消
# ---------------------------------------------------------------
@router.post("/activities/{activity_id}/register", summary="学生报名活动")
def register_activity(
    activity_id: int,
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """学生报名（REQ-06）。校验角色、活动状态、名额、重复报名，事务内写入。"""
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="仅学生可报名活动")

    act = _load_activity(db, activity_id)

    # 状态校验（REQ-08）：已取消 / 已截止的活动不能报名
    status = calc_status(act["start_time"], act["is_cancelled"])
    if status != "报名中":
        raise HTTPException(status_code=400, detail=f"活动当前状态为「{status}」，无法报名")

    # 事务内：先检查重复与名额，再写入，保证并发安全
    try:
        db.execute("BEGIN")
        dup = db.execute(
            "SELECT id FROM registrations WHERE activity_id = ? AND user_id = ?",
            (activity_id, user["id"]),
        ).fetchone()
        if dup:
            raise HTTPException(status_code=400, detail="你已报名该活动，不能重复报名")

        if _count_registered(db, activity_id) >= act["capacity"]:
            raise HTTPException(status_code=400, detail="报名人数已满")

        db.execute(
            "INSERT INTO registrations (activity_id, user_id) VALUES (?, ?)",
            (activity_id, user["id"]),
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except sqlite3.IntegrityError:
        # UNIQUE 约束兜底（极端并发下重复报名）
        db.rollback()
        raise HTTPException(status_code=400, detail="你已报名该活动，不能重复报名")

    return {"message": "报名成功", "activity_id": activity_id}


@router.delete("/activities/{activity_id}/register", summary="学生取消报名")
def unregister_activity(
    activity_id: int,
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """学生取消自己某活动的报名（REQ-06），名额随即释放。"""
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="仅学生可取消报名")

    _load_activity(db, activity_id)
    cur = db.execute(
        "DELETE FROM registrations WHERE activity_id = ? AND user_id = ?",
        (activity_id, user["id"]),
    )
    db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=400, detail="你尚未报名该活动")
    return {"message": "已取消报名"}


# ---------------------------------------------------------------
# 我的活动（按角色）
# ---------------------------------------------------------------
@router.get("/my-activities", summary="我的活动")
def my_activities(
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """按角色返回：
    - 学生：我报名过的活动列表
    - 教师：我发布的活动列表（附带报名人数）
    """
    if user["role"] == "student":
        # 学生：JOIN 报名表取已报名活动
        rows = db.execute(
            "SELECT a.* FROM activities a "
            "JOIN registrations r ON r.activity_id = a.id "
            "WHERE r.user_id = ? ORDER BY a.start_time",
            (user["id"],),
        ).fetchall()
        return {"activities": [activity_to_dict(db, r) for r in rows]}

    # 教师：自己发布的全部活动
    rows = db.execute(
        "SELECT * FROM activities WHERE creator_id = ? ORDER BY created_at DESC",
        (user["id"],),
    ).fetchall()
    return {"activities": [activity_to_dict(db, r) for r in rows]}


# ---------------------------------------------------------------
# 教师查看报名名单
# ---------------------------------------------------------------
@router.get("/activities/{activity_id}/registrations", summary="查看活动报名名单")
def list_registrations(
    activity_id: int,
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """查看活动报名名单：
    - 教师：仅能查看自己创建的活动（REQ-04 掌握报名情况）
    - 管理员：可查看任意活动（满足管理需求）
    - 学生：拒绝（学生查看自己的已报名活动由 /api/my-activities 提供）
    """
    if user["role"] not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="无权查看报名名单")

    act = _load_activity(db, activity_id)

    # 教师仅看自己发布的活动（管理员看任意）
    if user["role"] == "teacher" and act["creator_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="只能查看自己发布的活动")

    rows = db.execute(
        "SELECT u.id, u.username, u.name FROM registrations r "
        "JOIN users u ON u.id = r.user_id "
        "WHERE r.activity_id = ? ORDER BY r.created_at",
        (activity_id,),
    ).fetchall()
    return {"activity_id": activity_id, "students": [dict(r) for r in rows]}
