"""
routers/users.py —— 用户模块接口（REQ-01 注册 / REQ-02 登录）

接口：
- POST /api/register  注册（学号/工号 + 姓名 + 密码 + 角色）
- POST /api/login     登录（返回 token 与用户信息）
- GET  /api/me        查询当前登录用户
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import create_token, get_current_user, hash_password, verify_password
from backend.database import get_db

router = APIRouter(prefix="/api", tags=["用户"])


# ---------------------------------------------------------------
# 请求体模型
# ---------------------------------------------------------------
class RegisterRequest(BaseModel):
    """注册请求：username=学号/工号，role 只能选 student/teacher。"""
    username: str = Field(min_length=2, max_length=32, description="学号/工号")
    name: str = Field(min_length=1, max_length=32, description="姓名")
    password: str = Field(min_length=6, max_length=64, description="密码（至少6位）")
    role: str = Field(description="角色：student 或 teacher")


class LoginRequest(BaseModel):
    """登录请求。"""
    username: str
    password: str


def user_dict(user: sqlite3.Row) -> dict:
    """用户行转接口字典（绝不返回 password_hash）。"""
    return {
        "id": user["id"],
        "username": user["username"],
        "name": user["name"],
        "role": user["role"],
        "is_active": bool(user["is_active"]),
        "created_at": user["created_at"],
    }


# ---------------------------------------------------------------
# 接口实现
# ---------------------------------------------------------------
@router.post("/register", summary="用户注册")
def register(req: RegisterRequest, db: sqlite3.Connection = Depends(get_db)):
    """注册新用户：角色合法、用户名不重复、密码哈希存储后落库。"""
    # 校验角色合法性（fail-closed：白名单）
    if req.role not in ("student", "teacher"):
        raise HTTPException(status_code=400, detail="角色必须为 student 或 teacher")

    exists = db.execute(
        "SELECT id FROM users WHERE username = ?", (req.username,)
    ).fetchone()
    if exists:
        raise HTTPException(status_code=400, detail="该学号/工号已被注册")

    cur = db.execute(
        "INSERT INTO users (username, name, password_hash, role) VALUES (?, ?, ?, ?)",
        (req.username, req.name, hash_password(req.password), req.role),
    )
    db.commit()
    return {"message": "注册成功", "user_id": cur.lastrowid}


@router.post("/login", summary="用户登录")
def login(req: LoginRequest, db: sqlite3.Connection = Depends(get_db)):
    """登录：校验密码，成功后签发 token 并返回。"""
    user = db.execute(
        "SELECT * FROM users WHERE username = ?", (req.username,)
    ).fetchone()
    # 统一报错文案，避免暴露"用户是否存在"（防用户名探测）
    if user is None or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    # 管理员禁用账号后拒绝登录（REQ-09）
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="账号已被禁用，请联系管理员")

    token = create_token(user["id"])
    return {"token": token, "user": user_dict(user)}


@router.get("/me", summary="当前登录用户")
def me(user: sqlite3.Row = Depends(get_current_user)):
    """返回当前登录用户信息（依赖 get_current_user 完成 token 校验）。"""
    return user_dict(user)
