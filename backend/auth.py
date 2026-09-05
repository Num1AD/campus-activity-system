"""
auth.py —— 认证与安全模块

职责（对应 docs/04-软件设计.md 4.4 决策 3/4）：
1. 密码加盐哈希：SHA-256 + 随机盐，存储格式 "盐$摘要"，绝不存明文
2. token 签发与校验：登录成功后签发随机 token，服务端内存维护 token→用户映射
   （决策 4：实验规模用内存 token，重启后需重新登录，README 中已说明局限）
3. get_current_user：FastAPI 依赖，从 Authorization: Bearer <token> 中解析用户
"""

import hashlib
import secrets
import sqlite3
from datetime import datetime

from fastapi import Depends, Header, HTTPException

from backend.database import get_db

# ---------------------------------------------------------------
# token 存储：{token: user_id}（内存态，重启清空，属已知局限）
# ---------------------------------------------------------------
TOKENS: dict[str, int] = {}


# ---------------------------------------------------------------
# 密码哈希
# ---------------------------------------------------------------
def hash_password(password: str) -> str:
    """生成加盐哈希，格式：{16字节hex盐}${sha256摘要}。"""
    salt = secrets.token_hex(16)                          # 随机盐
    digest = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码：从存储串取出盐，重算摘要后比对。"""
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    return hashlib.sha256((salt + password).encode()).hexdigest() == digest


# ---------------------------------------------------------------
# token 签发与校验
# ---------------------------------------------------------------
def create_token(user_id: int) -> str:
    """为指定用户签发一个新 token 并登记。"""
    token = secrets.token_hex(32)                         # 256 位随机 token
    TOKENS[token] = user_id
    return token


def _current_time() -> str:
    """当前时间字符串（与数据库存储格式一致）。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def get_current_user(
    authorization: str = Header(default=""),
    db: sqlite3.Connection = Depends(get_db),
) -> sqlite3.Row:
    """
    FastAPI 依赖：解析请求头 Authorization: Bearer <token>，
    校验 token 并返回对应用户行。无效则抛 401。
    """
    # 解析 "Bearer xxx"
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录或登录已失效")
    token = authorization.removeprefix("Bearer ").strip()

    user_id = TOKENS.get(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="未登录或登录已失效")

    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    # 账号被管理员禁用后，其已有 token 立即失效（fail-closed）
    if not user["is_active"]:
        raise HTTPException(status_code=401, detail="账号已被禁用，请联系管理员")
    return user


def require_admin(user=Depends(get_current_user)) -> sqlite3.Row:
    """FastAPI 依赖：校验当前用户是管理员，否则 403（REQ-09）。"""
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可执行此操作")
    return user
