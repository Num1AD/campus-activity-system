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

# 报名状态常量（V2.0 新增）
# 对应 R-01 候补通道 / R-03 状态区分 / R-06 报名审核
# 数据库存英文标识，接口统一返回中文，与活动状态的口径保持一致
REG_PENDING    = "pending"      # 待审核：需审核活动的报名提交后，结果尚未确定
REG_CONFIRMED  = "confirmed"    # 正式参加：无需审核且有名额，或审核通过且有名额
REG_WAITLISTED = "waitlisted"   # 候补中：提交时名额已满，等待空余位置

REG_STATUS_TEXT = {
    REG_PENDING:    "待审核",
    REG_CONFIRMED:  "正式参加",
    REG_WAITLISTED: "候补中",
}

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


def reg_status_text(status: str) -> str:
    """把报名状态的英文标识转成中文展示文案。"""
    return REG_STATUS_TEXT.get(status, status)


def count_registrations(db: sqlite3.Connection, activity_id: int, status: str | None = None) -> int:
    """
    统计某活动的报名人数。

    status 为 None 时统计全部记录，否则只统计指定状态。
    名额口径（对应 R-03，第八章规则 1）：正式参加人数只统计 confirmed，
    候补与待审核都不占用名额。
    """
    if status is None:
        sql = "SELECT COUNT(*) AS n FROM registrations WHERE activity_id = ?"
        params: tuple = (activity_id,)
    else:
        sql = "SELECT COUNT(*) AS n FROM registrations WHERE activity_id = ? AND status = ?"
        params = (activity_id, status)
    return db.execute(sql, params).fetchone()["n"]


def activity_to_dict(db: sqlite3.Connection, row: sqlite3.Row) -> dict:
    """
    把 activities 表的一行转换为接口返回字典：
    附带正式报名人数、候补人数、待审核人数、剩余名额、动态状态与发布教师姓名。

    V2.0 调整：registered 只统计正式参加，候补与待审核不计入占位。
    否则候补人数会被算作已占用名额，剩余名额会算少，进而导致误判"已满"。
    """
    confirmed = count_registrations(db, row["id"], REG_CONFIRMED)
    waitlisted = count_registrations(db, row["id"], REG_WAITLISTED)
    pending = count_registrations(db, row["id"], REG_PENDING)
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
        "require_review": bool(row["require_review"]),
        "eligibility": row["eligibility"],
        "creator_id": row["creator_id"],
        "creator_name": creator_name,
        "status": status,
        "registered": confirmed,        # 已报名人数＝正式参加人数
        "waitlisted": waitlisted,       # 候补中的人数
        "pending_review": pending,      # 待审核的人数
        "remaining": max(row["capacity"] - confirmed, 0),
    }
