# -*- coding: utf-8 -*-
"""
_v3_check.py —— V3.0 新增能力验证（R3-01 / R3-02）

验证内容：
  A. 状态变更事件被正确记录（报名三种分支 / 审核三条路径 / 取消 / 递补）
  B. 事件不参与名额判定（加事件后名额口径仍是"只算正式参加"）
  C. 候补排队位置与队列总数正确，退出后依次前移
  D. 未读数：教师或系统触发才 +1，本人操作不计数；标记已读后清零
  E. 重复报名返回 409 且带当前状态
  F. 角色边界：教师与管理员访问学生专属接口返回 403

可重复运行：每次先清理标题带【V3验证】的旧活动，再新建。
"""
import sys
import time

import requests

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8000"
PREFIX = "【V3验证】"
PASS = FAIL = 0


def chk(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  " + detail) if detail else ""))
    else:
        FAIL += 1
        print("  [FAIL] %s  %s" % (name, detail))


def login(u, p="123456"):
    r = requests.post(BASE + "/api/login", json={"username": u, "password": p}, timeout=5)
    r.raise_for_status()
    return r.json()["token"]


def H(tk):
    return {"Authorization": "Bearer " + tk}


def reg_user(username, name):
    """注册一个临时学生并登录，返回 (token, user_id)。已存在则直接登录。"""
    requests.post(BASE + "/api/register", json={
        "username": username, "name": name, "password": "abc123", "role": "student",
    }, timeout=5)
    r = requests.post(BASE + "/api/login",
                      json={"username": username, "password": "abc123"}, timeout=5)
    data = r.json()
    return data["token"], data["user"]["id"]


def mk_activity(teacher_tk, title, capacity, require_review=False, day=20):
    r = requests.post(BASE + "/api/activities", headers=H(teacher_tk), json={
        "title": PREFIX + title,
        "description": "V3.0 自动验证用活动",
        "location": "自动验证场地",
        "start_time": "2026-12-%02d 10:00" % day,
        "end_time": "2026-12-%02d 12:00" % day,
        "capacity": capacity,
        "require_review": require_review,
        "eligibility": "",
    }, timeout=5)
    assert r.status_code == 200, r.text
    return r.json()["activity_id"]


def events_of(tk, aid):
    r = requests.get(BASE + "/api/my-registration-events", headers=H(tk), timeout=5)
    return [e for e in r.json()["events"] if e["activity_id"] == aid], r.json()["unread_count"]


def wait_ready():
    for _ in range(30):
        try:
            requests.get(BASE + "/api/health", timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False


def main():
    if not wait_ready():
        print("服务未就绪，请先启动后端")
        return 1

    tk_t = login("teacher01")
    tk_s1 = login("student01")
    tk_s2 = login("student02")
    tk_a = login("admin01")
    tk_s3, uid3 = reg_user("20261234", "验证学生三")

    # 清理上一轮遗留，保证可重复运行
    acts = requests.get(BASE + "/api/activities", timeout=5).json()["activities"]
    old = [a["id"] for a in acts if a["title"].startswith(PREFIX)]
    for aid in old:
        requests.post(BASE + f"/api/activities/{aid}/cancel", headers=H(tk_t), timeout=5)
    print("已清理上轮验证活动 %d 个\n" % len(old))

    # ---------------- A. 事件记录 ----------------
    print("【A】状态变更事件被正确记录")
    aid1 = mk_activity(tk_t, "有余额报名", capacity=5, day=20)
    requests.post(BASE + f"/api/activities/{aid1}/register", headers=H(tk_s1), timeout=5)
    ev, _ = events_of(tk_s1, aid1)
    chk("报名写入 1 条事件", len(ev) == 1, "实际 %d 条" % len(ev))
    chk("事件为 apply → confirmed",
        ev and ev[0]["reason_text"] == "提交报名" and ev[0]["to_status_text"] == "正式参加",
        str(ev[:1]))

    aid2 = mk_activity(tk_t, "满员进候补", capacity=1, day=21)
    requests.post(BASE + f"/api/activities/{aid2}/register", headers=H(tk_s1), timeout=5)
    requests.post(BASE + f"/api/activities/{aid2}/register", headers=H(tk_s2), timeout=5)
    ev2, _ = events_of(tk_s2, aid2)
    chk("满员报名事件为候补中",
        ev2 and ev2[0]["to_status_text"] == "候补中", str(ev2[:1]))

    aid3 = mk_activity(tk_t, "需审核报名", capacity=3, require_review=True, day=22)
    requests.post(BASE + f"/api/activities/{aid3}/register", headers=H(tk_s1), timeout=5)
    ev3, _ = events_of(tk_s1, aid3)
    chk("需审核报名事件为待审核",
        ev3 and ev3[0]["to_status_text"] == "待审核", str(ev3[:1]))

    # 审核三条路径
    requests.post(BASE + f"/api/activities/{aid3}/registrations/2/review",
                  headers=H(tk_t), json={"approve": True}, timeout=5)
    ev3, _ = events_of(tk_s1, aid3)
    chk("审核通过写事件且文案正确",
        len(ev3) == 2 and "审核通过" in ev3[1]["reason_text"], str([e["reason_text"] for e in ev3]))

    aid4 = mk_activity(tk_t, "审核拒绝", capacity=3, require_review=True, day=23)
    requests.post(BASE + f"/api/activities/{aid4}/register", headers=H(tk_s2), timeout=5)
    requests.post(BASE + f"/api/activities/{aid4}/registrations/3/review",
                  headers=H(tk_t), json={"approve": False}, timeout=5)
    ev4, _ = events_of(tk_s2, aid4)
    chk("审核拒绝写事件且文案为未通过",
        len(ev4) == 2 and ev4[1]["to_status_text"] == "报名未通过",
        str([e["to_status_text"] for e in ev4]))

    # 递补
    requests.delete(BASE + f"/api/activities/{aid2}/register", headers=H(tk_s1), timeout=5)
    ev2b, _ = events_of(tk_s2, aid2)
    chk("递补写 promoted 事件",
        any("递补" in e["reason_text"] for e in ev2b), str([e["reason_text"] for e in ev2b]))

    # 本人取消
    requests.delete(BASE + f"/api/activities/{aid1}/register", headers=H(tk_s1), timeout=5)
    ev1, _ = events_of(tk_s1, aid1)
    chk("本人取消写 withdraw 事件",
        len(ev1) == 2 and ev1[1]["to_status_text"] == "已取消报名",
        str([e["to_status_text"] for e in ev1]))

    # ---------------- B. 名额口径未被事件影响 ----------------
    print()
    print("【B】事件不参与名额判定")
    aid5 = mk_activity(tk_t, "名额口径", capacity=2, day=24)
    requests.post(BASE + f"/api/activities/{aid5}/register", headers=H(tk_s1), timeout=5)
    requests.post(BASE + f"/api/activities/{aid5}/register", headers=H(tk_s2), timeout=5)
    r = requests.post(BASE + f"/api/activities/{aid5}/register", headers=H(tk_s3), timeout=5)
    d = r.json()
    chk("容量 2 的第 3 人进候补（仍只算正式参加）",
        r.status_code == 200 and d["reg_status"] == "候补中", str(d)[:120])
    r = requests.get(BASE + f"/api/activities/{aid5}", timeout=5)
    a = r.json()
    chk("活动详情 registered=2 / remaining=0",
        a["registered"] == 2 and a["remaining"] == 0,
        "registered=%s remaining=%s" % (a["registered"], a["remaining"]))

    # ---------------- C. 排队位置 ----------------
    print()
    print("【C】候补排队位置")
    aid6 = mk_activity(tk_t, "排队位置", capacity=1, day=25)
    requests.post(BASE + f"/api/activities/{aid6}/register", headers=H(tk_s1), timeout=5)
    pos = {}
    for tk, label in [(tk_s2, "第二人"), (tk_s3, "第三人")]:
        r = requests.post(BASE + f"/api/activities/{aid6}/register", headers=H(tk), timeout=5)
        pos[label] = r.json().get("queue_position")
    chk("依次进入候补的位置为 1 / 2", pos == {"第二人": 1, "第三人": 2}, str(pos))

    r = requests.get(BASE + "/api/my-activities", headers=H(tk_s3), timeout=5)
    item = [x for x in r.json()["activities"] if x["id"] == aid6][0]
    chk("my-activities 返回位置与总人数",
        item["queue_position"] == 2 and item["waitlist_total"] == 2,
        "pos=%s total=%s" % (item["queue_position"], item["waitlist_total"]))

    requests.delete(BASE + f"/api/activities/{aid6}/register", headers=H(tk_s2), timeout=5)
    r = requests.get(BASE + "/api/my-activities", headers=H(tk_s3), timeout=5)
    item = [x for x in r.json()["activities"] if x["id"] == aid6][0]
    chk("前一位退出后位置前移为 1",
        item["queue_position"] == 1 and item["waitlist_total"] == 1,
        "pos=%s total=%s" % (item["queue_position"], item["waitlist_total"]))

    # ---------------- D. 未读计数 ----------------
    print()
    print("【D】未读数与标记已读")
    # 先清零
    requests.post(BASE + "/api/my-registration-events/read", headers=H(tk_s1), timeout=5)
    aid7 = mk_activity(tk_t, "未读计数", capacity=5, require_review=True, day=26)
    requests.post(BASE + f"/api/activities/{aid7}/register", headers=H(tk_s1), timeout=5)
    _, unread0 = events_of(tk_s1, aid7)
    chk("本人报名后未读仍为 0", unread0 == 0, "unread=%d" % unread0)
    requests.post(BASE + f"/api/activities/{aid7}/registrations/2/review",
                  headers=H(tk_t), json={"approve": True}, timeout=5)
    _, unread1 = events_of(tk_s1, aid7)
    chk("教师审核后未读变为 1", unread1 == 1, "unread=%d" % unread1)
    r = requests.post(BASE + "/api/my-registration-events/read", headers=H(tk_s1), timeout=5)
    chk("标记已读返回 0", r.status_code == 200 and r.json()["unread_count"] == 0, r.text[:100])
    _, unread2 = events_of(tk_s1, aid7)
    chk("复查未读为 0", unread2 == 0, "unread=%d" % unread2)

    # ---------------- E. 重复提交 ----------------
    print()
    print("【E】重复提交返回明确状态")
    r = requests.post(BASE + f"/api/activities/{aid7}/register", headers=H(tk_s1), timeout=5)
    body = r.json()
    detail = body.get("detail") or {}
    chk("重复报名返回 409", r.status_code == 409, "实际 %d" % r.status_code)
    # 该活动需审核，而且前面已审核通过，因此当前状态是"正式参加"
    chk("响应体含当前状态", detail.get("current_status") == "正式参加", str(detail)[:120])

    # ---------------- F. 角色边界 ----------------
    print()
    print("【F】角色边界")
    r = requests.get(BASE + "/api/my-registration-events", headers=H(tk_t), timeout=5)
    chk("教师访问 403", r.status_code == 403, "实际 %d" % r.status_code)
    r = requests.get(BASE + "/api/my-registration-events", headers=H(tk_a), timeout=5)
    chk("管理员访问 403", r.status_code == 403, "实际 %d" % r.status_code)
    r = requests.post(BASE + "/api/my-registration-events/read", headers=H(tk_t), timeout=5)
    chk("教师标记已读 403", r.status_code == 403, "实际 %d" % r.status_code)

    # 清理
    for aid in [aid1, aid2, aid3, aid4, aid5, aid6, aid7]:
        requests.post(BASE + f"/api/activities/{aid}/cancel", headers=H(tk_t), timeout=5)

    print()
    print("=" * 62)
    print("V3.0 验证结果：%d 项通过 / %d 项失败" % (PASS, FAIL))
    print("=" * 62)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
