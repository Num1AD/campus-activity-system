"""
routers/activities.py —— 活动模块接口（REQ-03 发布 / REQ-04 管理 / REQ-05 浏览）

接口：
- GET  /api/activities          活动列表（含剩余名额与状态，未登录可看）
- GET  /api/activities/{id}     活动详情
- POST /api/activities          教师发布活动
- PUT  /api/activities/{id}     教师编辑自己发布的活动
- POST /api/activities/{id}/cancel  教师取消自己发布的活动

权限模型（docs/04-软件设计.md 4.4 决策 1）：
- 浏览接口开放（REQ-05 决策：未登录可浏览）
- 写操作要求登录且角色为 teacher，且只能操作 creator_id = 自己的活动
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import get_current_user
from backend.database import get_db
from backend.helpers import activity_to_dict, now_str

router = APIRouter(prefix="/api", tags=["活动"])


# ---------------------------------------------------------------
# 请求体模型
# ---------------------------------------------------------------
class ActivityCreate(BaseModel):
    """发布活动请求。时间格式：YYYY-MM-DD HH:MM。"""
    title: str = Field(min_length=1, max_length=64, description="活动名称")
    description: str = Field(default="", max_length=1000, description="活动描述")
    location: str = Field(min_length=1, max_length=128, description="活动地点")
    start_time: str = Field(description="活动开始时间 YYYY-MM-DD HH:MM")
    end_time: str = Field(description="活动结束时间 YYYY-MM-DD HH:MM")
    capacity: int = Field(gt=0, le=10000, description="人数上限")


class ActivityUpdate(BaseModel):
    """编辑活动请求：所有字段可选，只更新传入项。"""
    title: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=1000)
    location: str | None = Field(default=None, max_length=128)
    start_time: str | None = None
    end_time: str | None = None
    capacity: int | None = Field(default=None, gt=0, le=10000)


# ---------------------------------------------------------------
# 权限辅助
# ---------------------------------------------------------------
def _require_teacher(user) -> None:
    """校验当前用户是教师，否则 403。"""
    if user["role"] != "teacher":
        raise HTTPException(status_code=403, detail="仅教师可执行此操作")


def _get_own_activity(db: sqlite3.Connection, activity_id: int, user) -> sqlite3.Row:
    """取活动并校验归属（creator_id 必须是当前用户），供教师管理接口复用。"""
    act = db.execute(
        "SELECT * FROM activities WHERE id = ?", (activity_id,)
    ).fetchone()
    if act is None:
        raise HTTPException(status_code=404, detail="活动不存在")
    if act["creator_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="只能管理自己发布的活动")
    return act


# ---------------------------------------------------------------
# 浏览接口（开放）
# ---------------------------------------------------------------
@router.get("/activities", summary="活动列表")
def list_activities(db: sqlite3.Connection = Depends(get_db)):
    """返回全部活动（含报名人数/剩余名额/状态），按开始时间升序。"""
    rows = db.execute(
        "SELECT * FROM activities ORDER BY start_time"
    ).fetchall()
    return {"activities": [activity_to_dict(db, r) for r in rows]}


@router.get("/activities/{activity_id}", summary="活动详情")
def get_activity(activity_id: int, db: sqlite3.Connection = Depends(get_db)):
    """返回单个活动详情。"""
    act = db.execute(
        "SELECT * FROM activities WHERE id = ?", (activity_id,)
    ).fetchone()
    if act is None:
        raise HTTPException(status_code=404, detail="活动不存在")
    return activity_to_dict(db, act)


# ---------------------------------------------------------------
# 教师写接口（登录 + 教师角色 + 归属校验）
# ---------------------------------------------------------------
@router.post("/activities", summary="教师发布活动")
def create_activity(
    req: ActivityCreate,
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """教师发布活动（REQ-03）。校验角色与时间合法性。"""
    _require_teacher(user)

    # 基础校验：开始时间必须晚于结束时间不可接受（fail-closed）
    if req.end_time <= req.start_time:
        raise HTTPException(status_code=400, detail="结束时间必须晚于开始时间")
    if req.start_time <= now_str():
        raise HTTPException(status_code=400, detail="开始时间必须晚于当前时间")

    cur = db.execute(
        "INSERT INTO activities (title, description, location, start_time, end_time, capacity, creator_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (req.title, req.description, req.location,
         req.start_time, req.end_time, req.capacity, user["id"]),
    )
    db.commit()
    return {"message": "发布成功", "activity_id": cur.lastrowid}


@router.put("/activities/{activity_id}", summary="教师编辑活动")
def update_activity(
    activity_id: int,
    req: ActivityUpdate,
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """教师编辑自己发布的活动（REQ-04）。仅更新传入的非空字段。"""
    _require_teacher(user)
    act = _get_own_activity(db, activity_id, user)

    # 已取消的活动不允许再编辑
    if act["is_cancelled"]:
        raise HTTPException(status_code=400, detail="已取消的活动不能编辑")

    # 收集需要更新的字段（动态 SQL，仅更新传入项）
    updates, params = [], []
    for field in ("title", "description", "location", "start_time", "end_time", "capacity"):
        value = getattr(req, field)
        if value is not None:
            updates.append(f"{field} = ?")
            params.append(value)
    if not updates:
        return {"message": "未提供需要更新的字段"}

    params.append(activity_id)
    db.execute(f"UPDATE activities SET {', '.join(updates)} WHERE id = ?", params)
    db.commit()
    return {"message": "修改成功"}


@router.post("/activities/{activity_id}/cancel", summary="教师取消活动")
def cancel_activity(
    activity_id: int,
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """教师取消自己发布的活动（REQ-04）：置 is_cancelled=1，学生端不再可报名。"""
    _require_teacher(user)
    act = _get_own_activity(db, activity_id, user)

    if act["is_cancelled"]:
        raise HTTPException(status_code=400, detail="活动已处于取消状态")

    db.execute(
        "UPDATE activities SET is_cancelled = 1 WHERE id = ?", (activity_id,)
    )
    db.commit()
    return {"message": "活动已取消"}
