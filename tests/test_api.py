"""
tests/test_api.py —— 阶段⑤软件验证自动化脚本

按 REQ-01~08 逐条设计 TEST 用例并执行，输出 PASS/FAIL 结果。
验证口径：对应需求 + 关键业务规则与异常场景（不止"能启动"）。

运行方式（后端已启动在 127.0.0.1:8000）：
    python tests/test_api.py

测试数据策略：
- 复用演示账号（teacher01/student01/student02，密码 123456）
- 注册一个临时学生账号验证注册流程
- 满员/已截止场景：临时创建容量 1 的活动 / 直接向库插入已过期的活动
- 测试结束后恢复数据库为初始演示状态（保证演示数据干净）
"""

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "backend" / "activity.db"

PASS = 0
FAIL = 0
RESULTS = []          # 收集 (编号, 对应需求, 场景, 预期, 实际, 结论)


def check(tid: str, req: str, scene: str, expected: str, actual, cond: bool):
    """记录一条用例结果。"""
    global PASS, FAIL
    verdict = "通过" if cond else "失败"
    if cond:
        PASS += 1
    else:
        FAIL += 1
    RESULTS.append((tid, req, scene, expected, str(actual), verdict))
    print(f"[{verdict}] {tid} ({req}) {scene}\n    预期: {expected}\n    实际: {actual}")


def post(path, payload=None, token=None):
    """POST 请求封装。"""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return requests.post(BASE + path, json=payload, headers=headers, timeout=5)


def get(path, token=None):
    """GET 请求封装。"""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return requests.get(BASE + path, headers=headers, timeout=5)


def login(username, password="123456"):
    """登录并返回 token。"""
    r = post("/api/login", {"username": username, "password": password})
    assert r.status_code == 200, f"预置登录失败: {username}"
    return r.json()["token"]


def insert_old_activity():
    """直接向数据库插入一个已截止（开始时间在过去）的活动，返回其 id。"""
    conn = sqlite3.connect(DB_PATH)
    try:
        past = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d %H:%M")
        cur = conn.execute(
            "INSERT INTO activities (title, description, location, start_time, end_time, capacity, creator_id) "
            "VALUES ('过期活动-测试', 'x', 'x', ?, ?, 10, "
            "(SELECT id FROM users WHERE username='teacher01'))",
            (past, past),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def reset_db():
    """测试结束恢复数据库初始演示状态。"""
    import importlib

    sys.path.insert(0, str(ROOT))
    from backend.database import init_db

    DB_PATH.unlink(missing_ok=True)
    init_db()
    print("\n[清理] 测试数据已清理，数据库恢复为初始演示状态")


def main():
    # ---------- 预置：登录演示账号 ----------
    teacher_tk = login("teacher01")
    stu1_tk = login("student01")
    stu2_tk = login("student02")

    # ===== REQ-01 用户注册 =====
    r = post("/api/register", {"username": "20269999", "name": "验证学生",
                               "password": "abc123", "role": "student"})
    check("TEST-01", "REQ-01", "新用户注册", "注册成功返回 user_id",
          r.json(), r.status_code == 200 and "user_id" in r.json())

    r = post("/api/register", {"username": "20269999", "name": "x",
                               "password": "abc123", "role": "student"})
    check("TEST-02", "REQ-01", "重复用户名注册", "返回 400 拒绝",
          r.json(), r.status_code == 400)

    r = post("/api/register", {"username": "20268888", "name": "x",
                               "password": "abc123", "role": "admin"})
    check("TEST-03", "REQ-01", "非法角色注册", "返回 400 拒绝",
          r.json(), r.status_code == 400)

    # ===== REQ-02 用户登录 =====
    r = post("/api/login", {"username": "20269999", "password": "abc123"})
    check("TEST-04", "REQ-02", "正确凭据登录", "返回 token 与用户信息",
          {k: r.json().get(k) for k in ("token", "user")}, r.status_code == 200 and "token" in r.json())

    r = post("/api/login", {"username": "20269999", "password": "wrong"})
    check("TEST-05", "REQ-02", "错误密码登录", "返回 401 拒绝",
          r.json(), r.status_code == 401)

    # ===== REQ-03 教师发布活动 =====
    future = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d %H:%M")
    future_end = (datetime.now() + timedelta(days=10, hours=2)).strftime("%Y-%m-%d %H:%M")
    payload = {"title": "验证用讲座", "description": "自动化验证", "location": "测试楼101",
               "start_time": future, "end_time": future_end, "capacity": 3}
    r = post("/api/activities", payload, teacher_tk)
    new_id = r.json().get("activity_id")
    check("TEST-06", "REQ-03", "教师发布活动", "发布成功返回 activity_id",
          r.json(), r.status_code == 200 and new_id)

    r = post("/api/activities", payload, stu1_tk)
    check("TEST-07", "REQ-03", "学生发布活动（越权）", "返回 403 拒绝",
          r.json(), r.status_code == 403)

    past = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    r = post("/api/activities", {**payload, "start_time": past}, teacher_tk)
    check("TEST-08", "REQ-03", "发布已过去时间的活动", "返回 400 拒绝",
          r.json(), r.status_code == 400)

    # ===== REQ-04 教师管理活动 =====
    r = requests.put(f"{BASE}/api/activities/{new_id}", json={"location": "改到报告厅201"},
                     headers={"Authorization": f"Bearer {teacher_tk}"}, timeout=5)
    check("TEST-09", "REQ-04", "教师编辑自己发布的活动", "返回修改成功",
          r.json(), r.status_code == 200)

    r = requests.put(f"{BASE}/api/activities/1", json={"location": "x"},
                     headers={"Authorization": f"Bearer {stu1_tk}"}, timeout=5)
    check("TEST-10", "REQ-04", "学生编辑活动（越权）", "返回 403 拒绝",
          r.json(), r.status_code == 403)

    r = get(f"/api/my-activities", teacher_tk)
    mine = r.json().get("activities", [])
    check("TEST-11", "REQ-04", "教师查看自己发布的活动列表", "列表包含新发布的活动",
          [a["title"] for a in mine], r.status_code == 200 and any(a["id"] == new_id for a in mine))

    # ===== REQ-05 学生浏览活动（未登录可浏览） =====
    r = get("/api/activities")
    acts = r.json().get("activities", [])
    check("TEST-12", "REQ-05", "未登录浏览活动列表", "返回活动列表（含剩余名额/状态）",
          f"{r.status_code} 共{len(acts)}条", r.status_code == 200 and len(acts) >= 3)

    r = get(f"/api/activities/{new_id}")
    d = r.json()
    check("TEST-13", "REQ-05", "查看活动详情", "含剩余名额与状态字段",
          d, r.status_code == 200 and "remaining" in d and "status" in d)

    # ===== REQ-06 学生报名 / 取消报名 =====
    r = post(f"/api/activities/{new_id}/register", None, stu1_tk)
    check("TEST-14", "REQ-06", "学生报名活动", "报名成功",
          r.json(), r.status_code == 200)

    r = post(f"/api/activities/{new_id}/register", None, stu1_tk)
    check("TEST-15", "REQ-08", "同一学生重复报名", "返回 400 拒绝",
          r.json(), r.status_code == 400)

    r = requests.delete(f"{BASE}/api/activities/{new_id}/register",
                        headers={"Authorization": f"Bearer {stu1_tk}"}, timeout=5)
    check("TEST-16", "REQ-06", "学生取消报名", "取消成功",
          r.json(), r.status_code == 200)

    r = requests.delete(f"{BASE}/api/activities/{new_id}/register",
                        headers={"Authorization": f"Bearer {stu1_tk}"}, timeout=5)
    check("TEST-17", "REQ-06", "未报名却取消", "返回 400 拒绝",
          r.json(), r.status_code == 400)

    # ===== REQ-07 我的活动 =====
    post(f"/api/activities/{new_id}/register", None, stu1_tk)  # 报名一个活动
    r = get("/api/my-activities", stu1_tk)
    mine1 = r.json().get("activities", [])
    check("TEST-18", "REQ-07", "学生我的活动列表", "包含刚报名的活动",
          [a["title"] for a in mine1], r.status_code == 200 and any(a["id"] == new_id for a in mine1))

    # ===== REQ-08 名额与状态约束 =====
    # 满员：发一个容量 1 的活动，两个学生报名，第二个应被拒
    small = post("/api/activities", {**payload, "title": "容量1验证活动", "capacity": 1}, teacher_tk).json()["activity_id"]
    post(f"/api/activities/{small}/register", None, stu1_tk)
    r = post(f"/api/activities/{small}/register", None, stu2_tk)
    check("TEST-19", "REQ-08", "名额满后报名", "返回 400 拒绝（报名人数已满）",
          r.json(), r.status_code == 400)

    # 已取消活动不可报名
    post(f"/api/activities/{small}/cancel", None, teacher_tk)
    r = post(f"/api/activities/{small}/register", None, stu2_tk)
    check("TEST-20", "REQ-08", "已取消活动报名", "返回 400 拒绝",
          r.json(), r.status_code == 400)

    # 已截止活动（开始时间在过去）不可报名
    old_id = insert_old_activity()
    r = post(f"/api/activities/{old_id}/register", None, stu2_tk)
    check("TEST-21", "REQ-08", "已截止活动报名", "返回 400 拒绝",
          r.json(), r.status_code == 400)

    # 教师查看报名名单（REQ-04 掌握报名情况）
    r = get(f"/api/activities/{new_id}/registrations", teacher_tk)
    names = [s["name"] for s in r.json().get("students", [])]
    check("TEST-22", "REQ-04", "教师查看报名名单", "名单包含报名学生姓名",
          names, r.status_code == 200 and "小明" in names)

    # ===== REQ-09 管理员账号管理 =====
    admin_tk = login("admin", "1234567")

    r = get("/api/admin/users", stu1_tk)
    check("TEST-23", "REQ-09", "非管理员访问管理接口（越权）", "返回 403 拒绝",
          r.json(), r.status_code == 403)

    r = get("/api/admin/users", admin_tk)
    users = r.json().get("users", [])
    roles = {u["role"] for u in users}
    check("TEST-24", "REQ-09", "管理员查看全部账号", "列表含 student/teacher/admin 角色",
          roles, r.status_code == 200 and {"student", "teacher", "admin"} <= roles)

    # 禁用 student02 → 登录被拒 → 启用 → 恢复登录
    stu2_id = [u["id"] for u in users if u["username"] == "student02"][0]
    r = requests.put(f"{BASE}/api/admin/users/{stu2_id}/status", json={"is_active": False},
                     headers={"Authorization": f"Bearer {admin_tk}"}, timeout=5)
    ok_disabled = r.status_code == 200
    r = post("/api/login", {"username": "student02", "password": "123456"})
    check("TEST-25", "REQ-09", "禁用后该账号无法登录", "返回 403 拒绝",
          r.json(), ok_disabled and r.status_code == 403)
    requests.put(f"{BASE}/api/admin/users/{stu2_id}/status", json={"is_active": True},
                 headers={"Authorization": f"Bearer {admin_tk}"}, timeout=5)
    r = post("/api/login", {"username": "student02", "password": "123456"})
    check("TEST-26", "REQ-09", "启用后账号恢复登录", "登录成功返回 token",
          "ok" if r.status_code == 200 else r.json(), r.status_code == 200)

    # 自我保护：管理员不能禁用/删除自己（取 admin 角色账号）
    admin_id = [u["id"] for u in users if u["role"] == "admin"][0]
    r = requests.put(f"{BASE}/api/admin/users/{admin_id}/status", json={"is_active": False},
                     headers={"Authorization": f"Bearer {admin_tk}"}, timeout=5)
    check("TEST-27", "REQ-09", "管理员禁用自己（保护）", "返回 400 拒绝",
          r.json(), r.status_code == 400)
    r = requests.delete(f"{BASE}/api/admin/users/{admin_id}",
                        headers={"Authorization": f"Bearer {admin_tk}"}, timeout=5)
    check("TEST-28", "REQ-09", "管理员删除自己（保护）", "返回 400 拒绝",
          r.json(), r.status_code == 400)

    # 删除学生账号（级联清理）
    r = requests.delete(f"{BASE}/api/admin/users/{stu2_id}",
                        headers={"Authorization": f"Bearer {admin_tk}"}, timeout=5)
    check("TEST-29", "REQ-09", "管理员删除学生账号", "删除成功",
          r.json(), r.status_code == 200)

    # ===== REQ-10 注册不开放管理员角色 =====
    r = post("/api/register", {"username": "20267777", "name": "x",
                               "password": "abc123", "role": "admin"})
    check("TEST-30", "REQ-10", "注册 admin 角色被拒", "返回 400 拒绝",
          r.json(), r.status_code == 400)

    # ===== 体验反馈新增：教师/管理员名单查看权限（REQ-04/09 体验完善）=====
    # TEST-31：管理员查看任意活动报名名单（不受发布人限制）
    r = get(f"/api/activities/{new_id}/registrations", admin_tk)
    admin_view = r.json().get("students", [])
    check("TEST-31", "REQ-09", "管理员查看任意活动报名名单",
          f"返回 200，含报名学生 {len(admin_view)} 人",
          r.json(), r.status_code == 200 and len(admin_view) >= 1)

    # TEST-32：教师查看他人活动报名名单（fail-closed：应 403）
    # 注册接口不开放教师角色 → 直接插数据库构造 teacher02 + 他发布的活动
    sys.path.insert(0, str(ROOT))
    from backend.auth import hash_password
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT INTO users (username, name, password_hash, role) VALUES (?, ?, ?, ?)",
            ("teacher02", "李老师", hash_password("123456"), "teacher"),
        )
        cur = conn.execute(
            "INSERT INTO activities (title, description, location, start_time, end_time, capacity, creator_id) "
            "VALUES ('李老师专属活动', '', '测试楼', ?, ?, 10, "
            "(SELECT id FROM users WHERE username='teacher02'))",
            (future, future_end),
        )
        t2_act_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    r = get(f"/api/activities/{t2_act_id}/registrations", teacher_tk)
    check("TEST-32", "REQ-04", "教师查看他人活动报名名单",
          "返回 403（fail-closed）", r.json(), r.status_code == 403)

    # TEST-33/34：教师/管理员均不应被允许报名（活动报名是学生专属能力）
    r = post(f"/api/activities/{new_id}/register", None, teacher_tk)
    check("TEST-33", "REQ-06", "教师点击报名（活动广场UI已隐藏，后端兜底）",
          "返回 403", r.json(), r.status_code == 403)
    r = post(f"/api/activities/{new_id}/register", None, admin_tk)
    check("TEST-34", "REQ-06", "管理员点击报名（活动广场UI已隐藏，后端兜底）",
          "返回 403", r.json(), r.status_code == 403)

    # ---------- 汇总 ----------
    print("\n" + "=" * 60)
    print(f"验证结果汇总：共 {len(RESULTS)} 条用例，通过 {PASS} 条，失败 {FAIL} 条")
    print("=" * 60)
    for tid, req, scene, exp, act, verdict in RESULTS:
        print(f"{tid} | {req} | {scene} | {verdict}")
    print("=" * 60)

    reset_db()
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
