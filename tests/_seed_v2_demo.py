"""
_seed_v2_demo.py —— 为前端实测准备 V2.0 演示场景（临时数据，验证后清理）

场景：
1. 「人工智能前沿讲座」容量 2、需审核、有参加资格 → 两个学生报名后由教师审核
   （一个转正式参加，一个因满员进入候补）
2. 「迎新志愿服务」容量 1、无需审核 → 一个正式、一个候补
"""

import sqlite3
import sys
from datetime import datetime, timedelta

import requests

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8000"
DB = "backend/activity.db"
FMT = "%Y-%m-%d %H:%M"
DEMO_TITLES = ("人工智能前沿讲座", "迎新志愿服务", "实验室安全培训", "摄影技巧分享会")

# ---- 先清理上一轮的演示数据（可重复执行） ----
conn = sqlite3.connect(DB)
ids = [r[0] for r in conn.execute(
    "SELECT id FROM activities WHERE title IN (%s)" % ",".join("?" * len(DEMO_TITLES)),
    DEMO_TITLES,
)]
if ids:
    conn.execute("DELETE FROM registrations WHERE activity_id IN (%s)" % ",".join("?" * len(ids)), ids)
    conn.execute("DELETE FROM activities WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)
    conn.commit()
conn.close()
print(f"已清理上一轮演示数据：{len(ids)} 个活动")


def login(u, p="123456"):
    r = requests.post(f"{BASE}/api/login", json={"username": u, "password": p}, timeout=5)
    assert r.status_code == 200, f"登录失败 {u}: {r.text}"
    return r.json()["token"]


def H(t):
    return {"Authorization": f"Bearer {t}"}


tk_t, tk_s1, tk_s2 = login("teacher01"), login("student01"), login("student02")


def mk(title, days, cap, review=False, elig=""):
    s = (datetime.now() + timedelta(days=days)).strftime(FMT)
    e = (datetime.now() + timedelta(days=days, hours=2)).strftime(FMT)
    r = requests.post(f"{BASE}/api/activities", json={
        "title": title, "description": "V2.0 功能演示数据", "location": "大学生活动中心",
        "start_time": s, "end_time": e, "capacity": cap,
        "require_review": review, "eligibility": elig,
    }, headers=H(tk_t), timeout=5)
    assert r.status_code == 200, r.text
    return r.json()["activity_id"]


sid1 = requests.get(f"{BASE}/api/me", headers=H(tk_s1), timeout=5).json()["id"]
sid2 = requests.get(f"{BASE}/api/me", headers=H(tk_s2), timeout=5).json()["id"]

# ---- 场景 1：需审核 + 资格，容量 2 ----
a1 = mk("人工智能前沿讲座", 9, 2, review=True, elig="仅限计算机相关专业学生")
requests.post(f"{BASE}/api/activities/{a1}/register", headers=H(tk_s1), timeout=5)
requests.post(f"{BASE}/api/activities/{a1}/register", headers=H(tk_s2), timeout=5)
requests.post(f"{BASE}/api/activities/{a1}/registrations/{sid1}/review",
              json={"approve": True}, headers=H(tk_t), timeout=5)
requests.post(f"{BASE}/api/activities/{a1}/registrations/{sid2}/review",
              json={"approve": True}, headers=H(tk_t), timeout=5)

# ---- 场景 2：无需审核，容量 1，先满后候补 ----
a2 = mk("迎新志愿服务", 12, 1)
requests.post(f"{BASE}/api/activities/{a2}/register", headers=H(tk_s1), timeout=5)
requests.post(f"{BASE}/api/activities/{a2}/register", headers=H(tk_s2), timeout=5)

# ---- 场景 3：留一条待审核，便于演示审核操作 ----
a3 = mk("实验室安全培训", 16, 30, review=True, elig="面向全体学生")
requests.post(f"{BASE}/api/activities/{a3}/register", headers=H(tk_s1), timeout=5)

# ---- 场景 4：容量 1 且已满，但 student02 没报名 ----
# 用于验证活动广场上「报名（进入候补）」的按钮文案
a4 = mk("摄影技巧分享会", 20, 1)
requests.post(f"{BASE}/api/activities/{a4}/register", headers=H(tk_s1), timeout=5)

print("演示数据已就绪：")
for aid, name in [(a1, "人工智能前沿讲座"), (a2, "迎新志愿服务"),
                  (a3, "实验室安全培训"), (a4, "摄影技巧分享会")]:
    d = requests.get(f"{BASE}/api/activities/{aid}", timeout=5).json()
    print(f"  #{aid} {name}: 正式 {d['registered']}/{d['capacity']} | 候补 {d['waitlisted']} | "
          f"待审核 {d['pending_review']} | 需审核 {d['require_review']}")

print()
print("学生视角预期：")
for u, tk in [("student01", tk_s1), ("student02", tk_s2)]:
    mine = requests.get(f"{BASE}/api/my-activities", headers=H(tk), timeout=5).json()["activities"]
    print(f"  {u}: " + "、".join(f"{a['title']}={a['reg_status']}" for a in mine))
