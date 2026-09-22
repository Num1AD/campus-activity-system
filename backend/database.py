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
-- 用户表：注册登录与角色识别（REQ-01/02；V2.0 扩展管理员角色与账号状态）
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,              -- 学号/工号，登录名
    name          TEXT    NOT NULL,                     -- 真实姓名
    password_hash TEXT    NOT NULL,                     -- 密码哈希（salt$digest，见 auth.py）
    -- V2.0：角色由两种扩展为三种（对应 R-08）
    role          TEXT    NOT NULL CHECK (role IN ('student', 'teacher', 'admin')),
    -- V2.0：账号是否可用，管理员停用异常账号时置 0（对应 R-08）
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 活动表：教师发布与管理（REQ-03/04/05；V2.0 增加审核开关与参加资格）
CREATE TABLE IF NOT EXISTS activities (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    title          TEXT    NOT NULL,                      -- 活动名称
    description    TEXT    NOT NULL DEFAULT '',           -- 活动描述
    location       TEXT    NOT NULL,                      -- 活动地点
    start_time     TEXT    NOT NULL,                      -- 活动开始时间（=报名截止时间点）
    end_time       TEXT    NOT NULL,                      -- 活动结束时间
    capacity       INTEGER NOT NULL CHECK (capacity > 0), -- 人数上限
    -- V2.0：该活动是否需要审核报名，由组织教师按活动决定（对应 R-06）
    require_review INTEGER NOT NULL DEFAULT 0,
    -- V2.0：参加资格条件说明，由教师填写、学生可见（对应 R-06）
    eligibility    TEXT    NOT NULL DEFAULT '',
    creator_id     INTEGER NOT NULL REFERENCES users(id), -- 发布教师
    is_cancelled   INTEGER NOT NULL DEFAULT 0,            -- 教师是否手动取消（1=取消）
    created_at     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 报名表：学生报名记录（REQ-06/07；V2.0 增加报名状态与进入候补时间）
CREATE TABLE IF NOT EXISTS registrations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id INTEGER NOT NULL REFERENCES activities(id),
    user_id     INTEGER NOT NULL REFERENCES users(id),
    -- V2.0：报名状态——pending 待审核 / confirmed 正式参加 / waitlisted 候补中
    -- （对应 R-01 候补通道、R-03 状态区分、R-06 审核）
    status      TEXT    NOT NULL DEFAULT 'confirmed'
                CHECK (status IN ('pending', 'confirmed', 'waitlisted')),
    -- V2.0：进入候补的时间，仅候补时写入，作为队列排序依据（对应 R-02）
    queued_at   TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),  -- 报名提交时间
    -- 唯一约束：同一学生不能重复报名同一活动（REQ-08，数据库层兜底）
    UNIQUE (activity_id, user_id)
);

-- 索引：按活动查报名、按学生查报名、按活动+状态统计正式人数
CREATE INDEX IF NOT EXISTS idx_reg_activity ON registrations(activity_id);
CREATE INDEX IF NOT EXISTS idx_reg_user     ON registrations(user_id);
CREATE INDEX IF NOT EXISTS idx_reg_status   ON registrations(activity_id, status);
CREATE INDEX IF NOT EXISTS idx_act_creator  ON activities(creator_id);
"""


# 演示活动模板：(标题, 地点, 开始距今天数, 时长小时, 容量, 是否需审核, 参加资格)
# 两个用途：① 首次建库时生成演示数据；② 每次启动时检查已过期的演示活动并顺延
DEMO_ACTIVITIES = [
    ("校园秋季篮球联赛", "东区篮球场",     30, 3, 30, 0, ""),
    ("Python 入门讲座",  "教学楼 301",     45, 2, 50, 0, ""),
    ("社团招新嘉年华",   "大学生活动中心", 60, 5, 100, 0, ""),
    # V2.0 演示场景：容量小，候补与待审核状态一打开就能看到，便于验收时直接演示
    ("人工智能前沿讲座", "图书馆报告厅",   20, 2, 3, 1, "仅限计算机相关专业学生"),
    ("摄影技巧分享会",   "艺术楼 205",     35, 2, 1, 0, ""),
]

# 演示报名记录：(活动标题, 学生账号, 报名状态)
# 目的是让三种报名状态在首次启动时都可见：待审核 / 正式参加 / 候补中
DEMO_REGISTRATIONS = [
    ("人工智能前沿讲座", "student01", "pending"),     # 待审核：教师可现场演示审核通过与拒绝
    ("摄影技巧分享会",   "student01", "confirmed"),   # 正式参加（容量 1，已占满）
    ("摄影技巧分享会",   "student02", "waitlisted"),  # 候补中：等待前者退出后递补
]


def get_connection() -> sqlite3.Connection:
    """创建新的数据库连接（每个请求用独立连接，避免多线程共用冲突）。"""
    # check_same_thread=False：FastAPI 的同步依赖在线程池中执行，
    # 依赖的收尾（yield 之后）不保证与创建时同一线程；每个请求各自持有独立连接，
    # 不存在跨线程共用，因此关闭线程检查是安全的。
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row          # 行按字段名访问，方便转 dict
    conn.execute("PRAGMA foreign_keys = ON")  # 开启外键约束
    return conn


def init_db() -> None:
    """建表；若无用户则写入演示数据；每次启动检查演示活动是否已过期并顺延。"""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA_SQL)

        # 仅当没有任何用户时才插入演示数据（避免重复 seed）
        has_users = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] > 0
        if not has_users:
            _seed(conn)

        # 演示活动过期检查：无论数据库放置多久，打开系统都应能演示报名与候补
        refreshed = _refresh_demo_activities(conn)
        if refreshed:
            print(f"[init_db] 演示活动已顺延到未来：{'、'.join(refreshed)}")

        conn.commit()
    finally:
        conn.close()


def _seed(conn: sqlite3.Connection) -> None:
    """写入演示账号与演示活动，便于本地开发与验证。"""
    # 导入 auth 放在函数内，避免模块循环依赖
    from backend.auth import hash_password

    # 演示账号（密码统一 123456）
    # V2.0 增加系统管理员账号（对应 R-08：平台账号与活动监督）
    demo_users = [
        ("teacher01", "王老师",   "teacher"),
        ("student01", "小明",     "student"),
        ("student02", "小红",     "student"),
        ("admin01",   "系统管理员", "admin"),
    ]
    user_ids = {}
    for username, name, role in demo_users:
        cur = conn.execute(
            "INSERT INTO users (username, name, password_hash, role) VALUES (?, ?, ?, ?)",
            (username, name, hash_password("123456"), role),
        )
        user_ids[username] = cur.lastrowid

    # 演示活动：以当前时间为基准生成未来活动（模板见模块顶部 DEMO_ACTIVITIES）
    now = datetime.now()
    fmt = "%Y-%m-%d %H:%M"
    creator_id = user_ids["teacher01"]
    act_ids = {}
    for title, location, days, hours, capacity, require_review, eligibility in DEMO_ACTIVITIES:
        cur = conn.execute(
            "INSERT INTO activities "
            "(title, description, location, start_time, end_time, capacity, "
            " require_review, eligibility, creator_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (title, "由演示教师发布的示例活动。", location,
             (now + timedelta(days=days)).strftime(fmt),
             (now + timedelta(days=days, hours=hours)).strftime(fmt),
             capacity, require_review, eligibility, creator_id),
        )
        act_ids[title] = cur.lastrowid

    # 演示报名：让三种报名状态（待审核 / 正式参加 / 候补中）首次启动即可见
    queued_at = now.strftime(fmt)
    for title, username, status in DEMO_REGISTRATIONS:
        conn.execute(
            "INSERT INTO registrations (activity_id, user_id, status, queued_at) "
            "VALUES (?, ?, ?, ?)",
            (act_ids[title], user_ids[username], status,
             queued_at if status == "waitlisted" else None),
        )


def _refresh_demo_activities(conn: sqlite3.Connection) -> list:
    """
    把已经开始的演示活动顺延到未来，返回被顺延的标题列表。

    为什么要做这一步：演示数据只在首次建库时按「当前时间 + N 天」写入一次，
    如果数据库放置时间较长（例如作业提交到教师检查之间隔了几周），
    演示活动会全部变成「已截止」，无法演示报名与候补。
    每次启动时检查并顺延，保证任何时候打开系统都能正常演示。

    只处理标题在 DEMO_ACTIVITIES 白名单内的活动，用户自己创建的活动不受影响。
    """
    now = datetime.now()
    fmt = "%Y-%m-%d %H:%M"
    refreshed = []
    for title, location, days, hours, capacity, require_review, eligibility in DEMO_ACTIVITIES:
        row = conn.execute(
            "SELECT id, start_time FROM activities WHERE title = ?", (title,)
        ).fetchone()
        if row is None:
            continue
        try:
            start_dt = datetime.strptime(row["start_time"], fmt)
        except ValueError:
            start_dt = None                       # 格式异常时也视为需要顺延
        if start_dt is not None and start_dt > now:
            continue                              # 尚未过期，保持原样
        conn.execute(
            "UPDATE activities SET start_time = ?, end_time = ? WHERE id = ?",
            ((now + timedelta(days=days)).strftime(fmt),
             (now + timedelta(days=days, hours=hours)).strftime(fmt),
             row["id"]),
        )
        refreshed.append(title)
    return refreshed


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
