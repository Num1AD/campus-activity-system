"""
routers/admin.py —— 管理模块接口（REQ-09 管理员账号管理）

接口：
- GET    /api/admin/users                查看全部注册账号
- PUT    /api/admin/users/{user_id}/status  禁用/启用账号（is_active）
- DELETE /api/admin/users/{user_id}      删除账号（学生/教师，不可删管理员）

权限与安全规则：
- 所有接口要求 admin 角色（依赖 require_admin）
- 不可操作自己（防止管理员禁用/删除自己导致系统失控）
- admin 角色账号不可被禁用或删除（保证系统始终有管理能力，fail-closed）
- 删除学生账号前级联删除其报名记录（外键约束）
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.auth import require_admin
from backend.database import get_db
from backend.routers.users import user_dict

router = APIRouter(prefix="/api/admin", tags=["管理"])


class StatusUpdate(BaseModel):
    """禁用/启用请求。"""
    is_active: bool


def _load_user(db: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    """按 id 取用户，不存在则 404。"""
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


def _check_operable(target: sqlite3.Row, admin_id: int) -> None:
    """校验目标账号可被管理：不能操作自己，不能操作 admin。"""
    if target["id"] == admin_id:
        raise HTTPException(status_code=400, detail="不能操作自己的账号")
    if target["role"] == "admin":
        raise HTTPException(status_code=400, detail="管理员账号不可被禁用或删除")


@router.get("/users", summary="查看全部账号")
def list_users(
    admin=Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
):
    """返回全部注册账号列表（不含密码哈希），按注册时间倒序。"""
    rows = db.execute(
        "SELECT * FROM users ORDER BY created_at DESC"
    ).fetchall()
    return {"users": [user_dict(r) for r in rows]}


@router.put("/users/{user_id}/status", summary="禁用/启用账号")
def set_user_status(
    user_id: int,
    req: StatusUpdate,
    admin=Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
):
    """禁用（is_active=false）或启用（is_active=true）一个学生/教师账号（REQ-09）。"""
    target = _load_user(db, user_id)
    _check_operable(target, admin["id"])

    db.execute(
        "UPDATE users SET is_active = ? WHERE id = ?",
        (1 if req.is_active else 0, user_id),
    )
    db.commit()
    action = "启用" if req.is_active else "禁用"
    return {"message": f"账号已{action}", "user_id": user_id, "is_active": req.is_active}


@router.delete("/users/{user_id}", summary="删除账号")
def delete_user(
    user_id: int,
    admin=Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
):
    """删除学生/教师账号（REQ-09）。外键级联清理：
    - 该用户发布的活动：先删活动报名记录，再删活动
    - 该用户自己的报名记录
    - 最后删除用户
    """
    target = _load_user(db, user_id)
    _check_operable(target, admin["id"])

    # 级联清理（外键约束：registrations/activities 均引用 users.id）
    act_ids = [
        r["id"]
        for r in db.execute("SELECT id FROM activities WHERE creator_id = ?", (user_id,)).fetchall()
    ]
    for aid in act_ids:
        db.execute("DELETE FROM registrations WHERE activity_id = ?", (aid,))
    db.execute("DELETE FROM activities WHERE creator_id = ?", (user_id,))
    db.execute("DELETE FROM registrations WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    return {"message": "账号已删除", "user_id": user_id}
