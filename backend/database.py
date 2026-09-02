"""
database.py —— 数据库层（SQLite）

职责：
1. 管理 SQLite 连接（每个请求独立连接，开启外键约束）
2. 建表：users / activities / registrations 三张表（见 docs/04-软件设计.md 4.3）
3. 首次启动时写入演示数据，便于开发与验证

设计说明：
- 数据库文件位于 backend/activity.db（已在 .gitignore 中排除，不提交）
- 时间统一存储为字符串 "YYYY-MM-DD HH:MM"，字符串字典序即时间先后序
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# 数据库文件路径：backend/activity.db
DB_PATH = Path(__file__).resolve().parent / "activity.db"

# ---------------------------------------------------------------
# 建表 SQL
# ---------------------------------------------------------------
SCHEMA_SQL = """
-- 用户表：注册登录与角色识别（REQ-01/02）
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,              -- 学号/工号，登录名
    name          TEXT    NOT NULL,                     -- 真实姓名
    password_hash TEXT    NOT NULL,                     -- 密码哈希（salt$digest，见 auth.py）
    role          TEXT    NOT NULL CHECK (role IN ('student', 'teacher')),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 活动表：教师发布与管理（REQ-03/04/05）
CREATE TABLE IF NOT EXISTS activities (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT    NOT NULL,                      -- 活动名称
    description  TEXT    NOT NULL DEFAULT '',           -- 活动描述
    location     TEXT    NOT NULL,                      -- 活动地点
    start_time   TEXT    NOT NULL,                      -- 活动开始时间（=报名截止时间点）
    end_time     TEXT    NOT NULL,                      -- 活动结束时间
    capacity     INTEGER NOT NULL CHECK (capacity > 0), -- 人数上限
    creator_id   INTEGER NOT NULL REFERENCES users(id), -- 发布教师
    is_cancelled INTEGER NOT NULL DEFAULT 0,            -- 教师是否手动取消（1=取消）
    created_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 报名表：学生报名记录（REQ-06/07）
CREATE TABLE IF NOT EXISTS registrations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id INTEGER NOT NULL REFERENCES activities(id),
    user_id     INTEGER NOT NULL REFERENCES users(id),
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    -- 唯一约束：同一学生不能重复报名同一活动（REQ-08，数据库层兜底）
    UNIQUE (activity_id, user_id)
);

-- 索引：按活动查报名、按学生查报名
CREATE INDEX IF NOT EXISTS idx_reg_activity ON registrations(activity_id);
CREATE INDEX IF NOT EXISTS idx_reg_user     ON registrations(user_id);
CREATE INDEX IF NOT EXISTS idx_act_creator  ON activities(creator_id);
"""


def get_connection() -> sqlite3.Connection:
    """创建新的数据库连接（每个请求用独立连接，避免多线程共用冲突）。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row          # 行按字段名访问，方便转 dict
    conn.execute("PRAGMA foreign_keys = ON")  # 开启外键约束
    return conn


def init_db() -> None:
    """建表；若用户表为空则写入演示数据。"""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA_SQL)

        # 仅当没有任何用户时才插入演示数据（避免重复 seed）
        has_users = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] > 0
        if not has_users:
            _seed(conn)
        conn.commit()
    finally:
        conn.close()


def _seed(conn: sqlite3.Connection) -> None:
    """写入演示账号与演示活动，便于本地开发与验证。"""
    # 导入 auth 放在函数内，避免模块循环依赖
    from backend.auth import hash_password

    # 演示账号（密码统一 123456）
    demo_users = [
        ("teacher01", "王老师", "teacher"),
        ("student01", "小明",   "student"),
        ("student02", "小红",   "student"),
    ]
    user_ids = {}
    for username, name, role in demo_users:
        cur = conn.execute(
            "INSERT INTO users (username, name, password_hash, role) VALUES (?, ?, ?, ?)",
            (username, name, hash_password("123456"), role),
        )
        user_ids[username] = cur.lastrowid

    # 演示活动：以当前时间为基准生成未来活动
    now = datetime.now()
    fmt = "%Y-%m-%d %H:%M"
    demo_activities = [
        # (标题, 地点, 开始, 结束, 容量, 发布者)
        ("校园秋季篮球联赛", "东区篮球场",
         (now + timedelta(days=7)).strftime(fmt), (now + timedelta(days=7, hours=3)).strftime(fmt), 30,
         user_ids["teacher01"]),
        ("Python 入门讲座", "教学楼 301",
         (now + timedelta(days=3)).strftime(fmt), (now + timedelta(days=3, hours=2)).strftime(fmt), 50,
         user_ids["teacher01"]),
        ("社团招新嘉年华", "大学生活动中心",
         (now + timedelta(days=14)).strftime(fmt), (now + timedelta(days=14, hours=5)).strftime(fmt), 100,
         user_ids["teacher01"]),
    ]
    for title, location, start_time, end_time, capacity, creator_id in demo_activities:
        conn.execute(
            "INSERT INTO activities (title, description, location, start_time, end_time, capacity, creator_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title, "由演示教师发布的示例活动。", location, start_time, end_time, capacity, creator_id),
        )


# 允许作为依赖使用的生成器：FastAPI 每请求调用一次，请求结束自动关闭连接
def get_db():
    """FastAPI 依赖：提供一个请求生命周期的数据库连接。"""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


if __name__ == "__main__":
    # 允许直接运行初始化：python -m backend.database
    init_db()
    print(f"数据库初始化完成：{DB_PATH}")
