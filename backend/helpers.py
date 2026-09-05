"""
helpers.py —— 活动行转字典与状态计算的公共函数

被 activities / registrations 两个路由复用，保证状态口径一致。
"""

import sqlite3
from datetime import datetime

# 活动状态常量（对应 docs/04-软件设计.md 4.4 决策 6：三态动态计算）
STATUS_OPEN      = "报名中"
STATUS_CLOSED    = "已截止"
STATUS_CANCELLED = "已取消"

FMT = "%Y-%m-%d %H:%M"


def now_str() -> str:
    """当前时间字符串，与活动时间字段格式一致。"""
    return datetime.now().strftime(FMT)


def calc_status(start_time: str, is_cancelled: int) -> str:
    """
    动态计算活动状态：
    - 教师取消 → 已取消
    - 当前时间 >= 活动开始时间 → 已截止（不再接受报名）
    - 其余 → 报名中
    """
    if is_cancelled:
        return STATUS_CANCELLED
    try:
        start_dt = datetime.strptime(start_time, FMT)
    except ValueError:
        return STATUS_CLOSED                      # 时间格式异常时保守视为已截止
    if datetime.now() >= start_dt:
        return STATUS_CLOSED
    return STATUS_OPEN


def activity_to_dict(db: sqlite3.Connection, row: sqlite3.Row) -> dict:
    """
    把 activities 表的一行转换为接口返回字典：
    附带报名人数、剩余名额、动态状态与发布教师姓名（creator_name）。
    """
    registered = db.execute(
        "SELECT COUNT(*) AS n FROM registrations WHERE activity_id = ?",
        (row["id"],),
    ).fetchone()["n"]
    status = calc_status(row["start_time"], row["is_cancelled"])
    # 发布教师姓名（活动卡片展示需要；三种身份都可见）
    creator = db.execute(
        "SELECT name FROM users WHERE id = ?", (row["creator_id"],)
    ).fetchone()
    creator_name = creator["name"] if creator else "未知"
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "location": row["location"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "capacity": row["capacity"],
        "creator_id": row["creator_id"],
        "creator_name": creator_name,
        "status": status,
        "registered": registered,
        "remaining": max(row["capacity"] - registered, 0),
    }
