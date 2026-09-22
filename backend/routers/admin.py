"""
routers/admin.py —— 系统管理员模块接口（V2.0 新增，R-08）

接口：
- GET  /api/admin/users                      查看平台用户账号及其角色
- POST /api/admin/users/{user_id}/status     停用 / 恢复账号
- POST /api/admin/activities/{id}/cancel     从平台层面处理违规或信息明显错误的活动

权限边界（对应报告第五章"角色与权限边界"管理员行）：
- 管理员负责平台层面的治理：账号状态与活动状态；
- 不代替教师组织或管理具体活动，不处理具体报名业务；
- 不修改教师设定的活动规则（人数上限、参加资格、是否需要审核）；
- 不擅自变更用户的角色归属。
本模块只提供上面三类操作，不提供任何报名/候补相关的写接口。
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import get_current_user
from backend.database import get_db
from backend.helpers import activity_to_dict

router = APIRouter(prefix="/api/admin", tags=["管理员"])


def _require_admin(user) -> None:
    """校验当前用户是系统管理员，否则 403。"""
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="仅系统管理员可执行此操作")


class StatusRequest(BaseModel):
    """账号状态变更请求。"""
    is_active: bool = Field(description="true=恢复为可用，false=停用")


@router.get("/users", summary="查看平台用户账号")
def list_users(
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """
    查看平台全部账号及其角色（R-08）。

    只返回账号基本情况与状态，不返回密码哈希；也不返回任何报名信息，
    报名业务不属于管理员的职责范围。
    """
    _require_admin(user)

    rows = db.execute(
        "SELECT id, username, name, role, is_active, created_at "
        "FROM users ORDER BY id"
    ).fetchall()

    users = [
        {
            "id": r["id"],
            "username": r["username"],
            "name": r["name"],
            "role": r["role"],
            "is_active": bool(r["is_active"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    return {
        "users": users,
        "total": len(users),
        "disabled": len([u for u in users if not u["is_active"]]),
    }


@router.post("/users/{user_id}/status", summary="停用或恢复账号")
def set_user_status(
    user_id: int,
    req: StatusRequest,
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """
    停用存在异常的账号，问题处理后可恢复为可用（R-08）。

    两条护栏（fail-closed）：
    - 管理员不能停用自己，避免把自己锁在系统外；
    - 被停用的账号即使此前签发的 token 仍在有效期内，也会在 get_current_user
      处被拒绝（见 auth.py），所以停用是立即生效的。
    """
    _require_admin(user)

    target = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if target is None:
        raise HTTPException(status_code=404, detail="账号不存在")

    if target["id"] == user["id"]:
        raise HTTPException(status_code=400, detail="不能停用当前登录的管理员账号")

    if bool(target["is_active"]) == req.is_active:
        state = "可用" if req.is_active else "停用"
        return {"message": f"该账号当前已是{state}状态，无需重复操作"}

    db.execute(
        "UPDATE users SET is_active = ? WHERE id = ?",
        (1 if req.is_active else 0, user_id),
    )
    db.commit()
    return {
        "message": "账号已恢复为可用" if req.is_active else "账号已停用",
        "user_id": user_id,
        "is_active": req.is_active,
    }


@router.post("/activities/{activity_id}/cancel", summary="平台层面取消违规活动")
def cancel_activity_by_admin(
    activity_id: int,
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """
    从平台层面处理违规或信息明显错误的活动（R-08）。

    与教师取消活动是同一个动作（置 is_cancelled），但入口与依据不同：
    教师基于自己的组织权限，管理员基于平台监督职责。
    管理员不能修改活动规则、不能调整报名名单，只能处置活动状态本身。
    """
    _require_admin(user)

    act = db.execute(
        "SELECT * FROM activities WHERE id = ?", (activity_id,)
    ).fetchone()
    if act is None:
        raise HTTPException(status_code=404, detail="活动不存在")
    if act["is_cancelled"]:
        raise HTTPException(status_code=400, detail="活动已处于取消状态")

    db.execute("UPDATE activities SET is_cancelled = 1 WHERE id = ?", (activity_id,))
    db.commit()
    return {
        "message": "活动已从平台层面取消",
        "activity_id": activity_id,
        "activity": activity_to_dict(db, db.execute(
            "SELECT * FROM activities WHERE id = ?", (activity_id,)
        ).fetchone()),
    }
