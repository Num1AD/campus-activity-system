"""
_v2_review_admin_check.py —— V2.0 报名审核（R-06/R-07）与管理员（R-08）端到端验证

覆盖报告第六章 US-06 / US-07 / US-08 的验收标准：
- US-06 正常：教师可设置资格与审核开关；需审核的报名进入待审核，结果对学生可见
- US-06 异常：活动已截止/已取消时不再接受新报名进入待审核
- US-06 权限：教师只能审核本人活动收到的报名；学生不能审核
- US-07 正常：先确认资格、再看剩余名额；通过时有名额→正式，满员→候补
- US-07 异常：审核未通过的报名不能参加该活动
- US-08 正常：管理员可查看全部账号及角色；可停用异常账号并恢复
- US-08 异常：停用后不能登录；恢复后可正常登录
- US-08 权限：管理员只处理账号与活动状态，不介入报名业务

用法：先启动后端服务，再执行本脚本。测试数据在结束时清理。
"""

import sqlite3
import sys
from datetime import datetime, timedelta

import requests

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8000"
DB = "backend/activity.db"
FMT = "%Y-%m-%d %H:%M"

PASS = FAIL = 0
FAILED = []


def chk(tag, name, expect, actual, ok):
    """打印一条检查结果。"""
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {tag} {name}")
    else:
        FAIL += 1
        FAILED.append(f"{tag} {name}（预期 {expect}，实际 {actual}）")
        print(f"  [FAIL] {tag} {name}  预期={expect}  实际={actual}")


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


def login(u, p="123456"):
    r = requests.post(f"{BASE}/api/login", json={"username": u, "password": p}, timeout=5)
    return r.json()["token"] if r.status_code == 200 else None


def register(u, name, role="student", p="123456"):
    return requests.post(
        f"{BASE}/api/register",
        json={"username": u, "name": name, "password": p, "role": role},
        timeout=5,
    )


def mk_activity(tok, title, days=6, capacity=2, require_review=False, eligibility=""):
    s = (datetime.now() + timedelta(days=days)).strftime(FMT)
    e = (datetime.now() + timedelta(days=days, hours=2)).strftime(FMT)
    return requests.post(
        f"{BASE}/api/activities",
        json={
            "title": title, "description": "", "location": "测试场地",
            "start_time": s, "end_time": e, "capacity": capacity,
            "require_review": require_review, "eligibility": eligibility,
        },
        headers=H(tok), timeout=5,
    )


print("=" * 78)
print("V2.0 报名审核与管理员功能验证")
print("=" * 78)

# ---------- 前置：准备账号 ----------
print()
print("【前置】准备测试账号")
for u, n in [("v2stu1", "测试学生一"), ("v2stu2", "测试学生二"), ("v2stu3", "测试学生三")]:
    register(u, n, "student")
register("v2tea2", "测试教师二", "teacher")

tk_t = login("teacher01")
tk_t2 = login("v2tea2")
tk_s1, tk_s2, tk_s3 = login("v2stu1"), login("v2stu2"), login("v2stu3")
tk_admin = login("admin01")
print(f"   teacher01={bool(tk_t)} v2tea2={bool(tk_t2)} 学生1/2/3={bool(tk_s1)}/{bool(tk_s2)}/{bool(tk_s3)} admin01={bool(tk_admin)}")

sid1 = requests.get(f"{BASE}/api/me", headers=H(tk_s1), timeout=5).json()["id"]
sid2 = requests.get(f"{BASE}/api/me", headers=H(tk_s2), timeout=5).json()["id"]
sid3 = requests.get(f"{BASE}/api/me", headers=H(tk_s3), timeout=5).json()["id"]

created_aids = []

# ---------- US-06 正常：审核开关与资格 ----------
print()
print("【US-06 正常流程】审核开关与参加资格可设置")
r = mk_activity(tk_t, "【V2.0】需审核活动", capacity=2, require_review=True,
                eligibility="仅限已完成报到的学生")
chk("US-06", "发布需审核的活动", 200, r.status_code, r.status_code == 200)
aid = r.json()["activity_id"]
created_aids.append(aid)

d = requests.get(f"{BASE}/api/activities/{aid}", timeout=5).json()
chk("US-06", "详情返回 require_review=True", True, d.get("require_review"), d.get("require_review") is True)
chk("US-06", "详情返回参加资格条件", "仅限已完成报到的学生", d.get("eligibility"),
    d.get("eligibility") == "仅限已完成报到的学生")

# 学生1 报名 → 待审核
r = requests.post(f"{BASE}/api/activities/{aid}/register", headers=H(tk_s1), timeout=5)
chk("US-06", "需审核活动报名返回待审核", "待审核", r.json().get("reg_status"),
    r.status_code == 200 and r.json().get("reg_status") == "待审核")

d = requests.get(f"{BASE}/api/activities/{aid}", timeout=5).json()
chk("US-06", "待审核不占正式名额（registered=0）", 0, d.get("registered"), d.get("registered") == 0)
chk("US-06", "待审核人数正确（pending_review=1）", 1, d.get("pending_review"), d.get("pending_review") == 1)
chk("US-06", "剩余名额未被占用（remaining=2）", 2, d.get("remaining"), d.get("remaining") == 2)

# 学生端可见自己的待审核状态
mine = requests.get(f"{BASE}/api/my-activities", headers=H(tk_s1), timeout=5).json()["activities"]
item = next((a for a in mine if a["id"] == aid), None)
chk("US-06", "学生端可见本人状态为待审核", "待审核",
    item.get("reg_status") if item else None,
    item is not None and item.get("reg_status") == "待审核")

# 教师名单按状态分组
lst = requests.get(f"{BASE}/api/activities/{aid}/registrations", headers=H(tk_t), timeout=5).json()
chk("US-06", "教师名单返回待审核分组", 1, lst.get("pending_count"), lst.get("pending_count") == 1)
chk("US-06", "名单中该生状态为待审核", "待审核",
    lst["students"][0].get("reg_status_text") if lst.get("students") else None,
    bool(lst.get("students")) and lst["students"][0].get("reg_status_text") == "待审核")

# ---------- US-06 权限：只能审核本人活动的报名 ----------
print()
print("【US-06 权限边界】")
r = requests.post(f"{BASE}/api/activities/{aid}/registrations/{sid1}/review",
                  json={"approve": True}, headers=H(tk_t2), timeout=5)
chk("US-06", "其他教师不能审核（403）", 403, r.status_code, r.status_code == 403)

r = requests.post(f"{BASE}/api/activities/{aid}/registrations/{sid1}/review",
                  json={"approve": True}, headers=H(tk_s1), timeout=5)
chk("US-06", "学生不能审核（403）", 403, r.status_code, r.status_code == 403)

r = requests.post(f"{BASE}/api/activities/{aid}/registrations/{sid1}/review",
                  json={"approve": True}, headers=H(tk_admin), timeout=5)
chk("US-06", "管理员不能审核（403）", 403, r.status_code, r.status_code == 403)

r = requests.post(f"{BASE}/api/activities/{aid}/registrations/999999/review",
                  json={"approve": True}, headers=H(tk_t), timeout=5)
chk("US-06", "审核未报名的学生 → 404", 404, r.status_code, r.status_code == 404)

# ---------- US-07 正常：通过后看名额 ----------
print()
print("【US-07 正常流程】先资格后名额")
r = requests.post(f"{BASE}/api/activities/{aid}/registrations/{sid1}/review",
                  json={"approve": True}, headers=H(tk_t), timeout=5)
chk("US-07", "初次通过且有剩余名额 → 正式参加", "正式参加", r.json().get("reg_status"),
    r.status_code == 200 and r.json().get("reg_status") == "正式参加")

# 学生2 报名（走审核）→ 通过 → 名额刚好还剩 1 → 正式参加
requests.post(f"{BASE}/api/activities/{aid}/register", headers=H(tk_s2), timeout=5)
r = requests.post(f"{BASE}/api/activities/{aid}/registrations/{sid2}/review",
                  json={"approve": True}, headers=H(tk_t), timeout=5)
chk("US-07", "第 2 人通过且名额刚好 → 正式参加", "正式参加", r.json().get("reg_status"),
    r.json().get("reg_status") == "正式参加")
d = requests.get(f"{BASE}/api/activities/{aid}", timeout=5).json()
chk("US-07", "正式人数达到上限（registered=2）", 2, d.get("registered"), d.get("registered") == 2)
chk("US-07", "剩余名额归零（remaining=0）", 0, d.get("remaining"), d.get("remaining") == 0)

# 学生3 报名 → 教师通过 → 满员 → 进入候补（R-07 关键规则）
requests.post(f"{BASE}/api/activities/{aid}/register", headers=H(tk_s3), timeout=5)
r = requests.post(f"{BASE}/api/activities/{aid}/registrations/{sid3}/review",
                  json={"approve": True}, headers=H(tk_t), timeout=5)
chk("US-07", "通过但名额已满 → 进入候补", "候补中", r.json().get("reg_status"),
    r.status_code == 200 and r.json().get("reg_status") == "候补中")
chk("US-07", "候补同时返回入队时间", True, bool(r.json().get("queued_at")), bool(r.json().get("queued_at")))

# 重复审核已处理的报名 → 400
r = requests.post(f"{BASE}/api/activities/{aid}/registrations/{sid3}/review",
                  json={"approve": True}, headers=H(tk_t), timeout=5)
chk("US-07", "对已处理的报名再次审核 → 400", 400, r.status_code, r.status_code == 400)

# 候补递补：正式学生取消 → 候补者自动转正式（审核 + 候补联动）
r = requests.delete(f"{BASE}/api/activities/{aid}/register", headers=H(tk_s1), timeout=5)
chk("US-07", "正式学生取消后队首候补自动递补", sid3, r.json().get("promoted_user_id"),
    r.json().get("promoted_user_id") == sid3)
lst = requests.get(f"{BASE}/api/activities/{aid}/registrations", headers=H(tk_t), timeout=5).json()
chk("US-07", "递补后正式 2 人、候补 0 人", (2, 0), (lst["confirmed_count"], lst["waitlisted_count"]),
    (lst["confirmed_count"], lst["waitlisted_count"]) == (2, 0))

# ---------- US-06 异常：审核未通过的不能参加 ----------
print()
print("【US-06 异常情形】拒绝报名")
r = mk_activity(tk_t, "【V2.0】审核拒绝测试", capacity=5, require_review=True,
                eligibility="仅限大二以上")
chk("US-06", "发布第二个需审核活动", 200, r.status_code, r.status_code == 200)
aid2 = r.json()["activity_id"]
created_aids.append(aid2)

requests.post(f"{BASE}/api/activities/{aid2}/register", headers=H(tk_s1), timeout=5)
r = requests.post(f"{BASE}/api/activities/{aid2}/registrations/{sid1}/review",
                  json={"approve": False}, headers=H(tk_t), timeout=5)
chk("US-06", "拒绝报名返回 rejected", "rejected", r.json().get("result"),
    r.status_code == 200 and r.json().get("result") == "rejected")

lst = requests.get(f"{BASE}/api/activities/{aid2}/registrations", headers=H(tk_t), timeout=5).json()
chk("US-06", "被拒绝的学生不在名单中", 0, len(lst.get("students", [])), len(lst.get("students", [])) == 0)

mine = requests.get(f"{BASE}/api/my-activities", headers=H(tk_s1), timeout=5).json()["activities"]
chk("US-06", "被拒后该生活动列表不含此活动", False,
    any(a["id"] == aid2 for a in mine), not any(a["id"] == aid2 for a in mine))

# 活动已截止时不能报名进入待审核
s_past = (datetime.now() - timedelta(days=1)).strftime(FMT)
e_past = (datetime.now() - timedelta(hours=20)).strftime(FMT)
conn = sqlite3.connect(DB)
conn.execute("INSERT INTO activities (title, description, location, start_time, end_time, capacity, "
             "require_review, eligibility, creator_id) VALUES (?,?,?,?,?,?,?,?,?)",
             ("【V2.0】已截止需审核活动", "", "x", s_past, e_past, 5, 1, "", 1))
conn.commit()
aid_past = conn.execute("SELECT id FROM activities WHERE title='【V2.0】已截止需审核活动'").fetchone()[0]
conn.close()
created_aids.append(aid_past)
r = requests.post(f"{BASE}/api/activities/{aid_past}/register", headers=H(tk_s1), timeout=5)
chk("US-06", "已截止活动不能报名进入待审核（400）", 400, r.status_code, r.status_code == 400)

# ---------- US-08 管理员 ----------
print()
print("【US-08 管理员功能】")
r = requests.get(f"{BASE}/api/admin/users", headers=H(tk_admin), timeout=5)
chk("US-08", "管理员可查看全部账号", 200, r.status_code, r.status_code == 200)
users = r.json()["users"] if r.status_code == 200 else []
roles = {u["role"] for u in users}
chk("US-08", "账号列表含三种角色", True, roles, {"student", "teacher", "admin"}.issubset(roles))
chk("US-08", "账号列表不含密码哈希", False, any("password" in u for u in users),
    not any("password" in u for u in users))

# 非管理员访问
r = requests.get(f"{BASE}/api/admin/users", headers=H(tk_t), timeout=5)
chk("US-08", "教师访问管理员接口 → 403", 403, r.status_code, r.status_code == 403)
r = requests.get(f"{BASE}/api/admin/users", headers=H(tk_s1), timeout=5)
chk("US-08", "学生访问管理员接口 → 403", 403, r.status_code, r.status_code == 403)
r = requests.get(f"{BASE}/api/admin/users", timeout=5)
chk("US-08", "未登录访问管理员接口 → 401", 401, r.status_code, r.status_code == 401)

# 管理员不能停用自己
admin_id = requests.get(f"{BASE}/api/me", headers=H(tk_admin), timeout=5).json()["id"]
r = requests.post(f"{BASE}/api/admin/users/{admin_id}/status",
                  json={"is_active": False}, headers=H(tk_admin), timeout=5)
chk("US-08", "管理员不能停用自己（400）", 400, r.status_code, r.status_code == 400)

# 停用学生1
r = requests.post(f"{BASE}/api/admin/users/{sid1}/status",
                  json={"is_active": False}, headers=H(tk_admin), timeout=5)
chk("US-08", "管理员可停用异常账号", 200, r.status_code, r.status_code == 200)

r = requests.post(f"{BASE}/api/login", json={"username": "v2stu1", "password": "123456"}, timeout=5)
chk("US-08", "停用后不能登录（403）", 403, r.status_code, r.status_code == 403)

r = requests.get(f"{BASE}/api/me", headers=H(tk_s1), timeout=5)
chk("US-08", "停用后已签发 token 立即失效（401）", 401, r.status_code, r.status_code == 401)

# 恢复
r = requests.post(f"{BASE}/api/admin/users/{sid1}/status",
                  json={"is_active": True}, headers=H(tk_admin), timeout=5)
chk("US-08", "管理员可恢复账号", 200, r.status_code, r.status_code == 200)
r = requests.post(f"{BASE}/api/login", json={"username": "v2stu1", "password": "123456"}, timeout=5)
chk("US-08", "恢复后可正常登录", 200, r.status_code, r.status_code == 200)
tk_s1 = r.json()["token"]

# 幂等
r = requests.post(f"{BASE}/api/admin/users/{sid1}/status",
                  json={"is_active": True}, headers=H(tk_admin), timeout=5)
chk("US-08", "重复恢复为幂等（200）", 200, r.status_code, r.status_code == 200)

# 管理员处理违规活动
r = requests.post(f"{BASE}/api/admin/activities/{aid2}/cancel", headers=H(tk_admin), timeout=5)
chk("US-08", "管理员可从平台层面取消活动", 200, r.status_code, r.status_code == 200)

# 管理员不能改活动规则（无此接口）
r = requests.put(f"{BASE}/api/activities/{aid2}", json={"capacity": 99}, headers=H(tk_admin), timeout=5)
chk("US-08", "管理员不能修改活动规则（403）", 403, r.status_code, r.status_code == 403)

# 管理员不介入报名业务：不能报名、不能审核
r = requests.post(f"{BASE}/api/activities/{aid}/register", headers=H(tk_admin), timeout=5)
chk("US-08", "管理员不能报名（403）", 403, r.status_code, r.status_code == 403)

# 管理员可只读查看报名与候补名单（用于监督，第八章设计约定）
r = requests.get(f"{BASE}/api/activities/{aid}/registrations", headers=H(tk_admin), timeout=5)
body = r.json() if r.status_code == 200 else {}
chk("US-08", "管理员可查看报名名单（200，且标记只读）", "200 且 readonly=true",
    f"{r.status_code} readonly={body.get('readonly')}",
    r.status_code == 200 and body.get("readonly") is True and "students" in body)

# 管理员对他人（非本人发布）的活动同样可只读查看
r = requests.get(f"{BASE}/api/activities/{aid2}/registrations", headers=H(tk_admin), timeout=5)
chk("US-08", "管理员可查看任意活动的名单", 200, r.status_code, r.status_code == 200)

# 只读边界：管理员仍不能审核报名
r = requests.post(f"{BASE}/api/activities/{aid}/registrations/{sid1}/review",
                  json={"approve": True}, headers=H(tk_admin), timeout=5)
chk("US-08", "管理员不能审核报名（403）", 403, r.status_code, r.status_code == 403)

# ---------- 清理 ----------
print()
conn = sqlite3.connect(DB)
conn.execute("DELETE FROM registrations WHERE activity_id IN (%s)" %
             ",".join(str(a) for a in created_aids))
conn.execute("DELETE FROM activities WHERE id IN (%s)" % ",".join(str(a) for a in created_aids))
conn.execute("DELETE FROM registrations WHERE user_id IN "
             "(SELECT id FROM users WHERE username LIKE 'v2stu%' OR username='v2tea2')")
conn.execute("DELETE FROM users WHERE username LIKE 'v2stu%' OR username='v2tea2'")
conn.commit()
left_u = [r[0] for r in conn.execute("SELECT username FROM users ORDER BY id")]
left_a = [r[0] for r in conn.execute("SELECT title FROM activities ORDER BY id")]
left_r = conn.execute("SELECT COUNT(*) FROM registrations").fetchone()[0]
conn.close()
print(f"测试数据已清理 → 账号 {left_u} / 活动 {left_a} / 报名 {left_r} 条")

print()
print("=" * 78)
print(f"结果：{PASS} 项通过 / {FAIL} 项失败")
if FAILED:
    print("失败明细：")
    for f in FAILED:
        print("  -", f)
print("=" * 78)
