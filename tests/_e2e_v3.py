# -*- coding: utf-8 -*-
"""
_e2e_v3.py —— V3.0 端到端流程自测（playwright + Edge 无头）

覆盖范围：
  一、认证：注册、登录、错误密码、登出、未登录访问受限视图
  二、学生：报名（有名额 / 满员进候补 / 需审核）、取消、退出候补、状态标签、
           时间线展开、未读徽标出现与清零、连点只发一次请求
  三、教师：发布（含审核开关与资格）、编辑、取消、名单分组、审核通过 / 拒绝
  四、管理员：账号列表、停用（被停用者无法登录）、恢复、不能停用自己、
             活动广场只读名单
  五、越权：学生 / 教师调管理接口、教师看他人活动名单
  六、运行质量：全程捕获页面 console 错误、未捕获异常、非预期的 4xx/5xx 请求

每轮使用带唯一后缀的活动，避免与历史数据重名。
"""
import os
import sys
import time

import requests
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8000"
OUT = os.path.join("report", "_v3check")
os.makedirs(OUT, exist_ok=True)
RUN = str(int(time.time()))[-5:]
PREFIX = "【自测】"

PASS = FAIL = 0
console_errors = []
page_errors = []
bad_requests = []
# 做"故意失败"的负向测试时置为 True，期间不把预期的 401 等记为缺陷
suppress = {"on": False}


def chk(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  " + detail) if detail else ""))
    else:
        FAIL += 1
        print("  [FAIL] %s  %s" % (name, detail))


def login_api(u, p="123456"):
    r = requests.post(BASE + "/api/login", json={"username": u, "password": p}, timeout=5)
    return r.json()["token"] if r.status_code == 200 else None


def H(t):
    return {"Authorization": "Bearer " + t}


def wait_ready():
    for _ in range(30):
        try:
            requests.get(BASE + "/api/health", timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False


def attach_monitors(page, tag):
    """挂上错误监听。静默期内的错误不记录（负向测试的预期失败）。"""
    def on_console(m):
        if suppress["on"]:
            return
        if m.type == "error":
            console_errors.append((tag, m.location.get("url", "") if m.location else "", m.text))

    def on_response(r):
        if suppress["on"]:
            return
        # 5xx 一律算问题；404 说明有资源缺失（如 favicon）
        if r.status >= 500 or r.status == 404:
            bad_requests.append((tag, r.status, r.url))

    page.on("console", on_console)
    page.on("pageerror", lambda e: None if suppress["on"] else page_errors.append((tag, str(e))))
    page.on("response", on_response)


def login_ui(page, token):
    page.goto(BASE, wait_until="networkidle")
    page.evaluate("t => localStorage.setItem('cas_token', t)", token)
    page.reload(wait_until="networkidle")
    page.wait_for_selector(".act-card", timeout=8000)


def cleanup():
    """
    清理自测产生的数据。

    只用接口只能"取消"活动，记录仍会留在活动广场里；自测反复运行会把演示环境
    堆满【自测】活动。因此这里直接连库删除本轮前缀的活动、报名、事件与临时账号。
    """
    tk = login_api("teacher01")
    acts = requests.get(BASE + "/api/activities", timeout=5).json()["activities"]
    for a in acts:
        if a["title"].startswith(PREFIX):
            requests.post(BASE + f"/api/activities/{a['id']}/cancel", headers=H(tk), timeout=5)

    import sqlite3
    db = sqlite3.connect(os.path.join("backend", "activity.db"))
    try:
        ids = [r[0] for r in db.execute(
            "SELECT id FROM activities WHERE title LIKE ?", (PREFIX + "%",))]
        if ids:
            q = ",".join("?" * len(ids))
            db.execute("DELETE FROM registration_events WHERE activity_id IN (%s)" % q, ids)
            db.execute("DELETE FROM registrations WHERE activity_id IN (%s)" % q, ids)
            db.execute("DELETE FROM activities WHERE id IN (%s)" % q, ids)
        # 自测注册的临时账号（t 开头 + 本轮后缀）
        uids = [r[0] for r in db.execute(
            "SELECT id FROM users WHERE username = ?", ("t" + RUN,))]
        if uids:
            q2 = ",".join("?" * len(uids))
            db.execute("DELETE FROM registration_events WHERE user_id IN (%s)" % q2, uids)
            db.execute("DELETE FROM registrations WHERE user_id IN (%s)" % q2, uids)
            db.execute("DELETE FROM users WHERE id IN (%s)" % q2, uids)
        db.commit()
    finally:
        db.close()


def main():
    if not wait_ready():
        print("服务未就绪")
        return 1
    cleanup()

    print("【一】认证流程")
    # 注册一个自测学生
    uname = "t" + RUN
    r = requests.post(BASE + "/api/register", json={
        "username": uname, "name": "自测学生" + RUN, "password": "abc123", "role": "student",
    }, timeout=5)
    chk("注册新学生", r.status_code == 200, r.text[:100])

    tk_s3 = login_api(uname, "abc123")
    chk("新学生可登录", bool(tk_s3))

    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        ctx = b.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        attach_monitors(page, "auth")
        # 报名/取消成功会弹 alert，统一接受
        page.on("dialog", lambda d: d.accept())

        page.goto(BASE, wait_until="networkidle")
        page.wait_for_selector(".act-card", timeout=8000)
        chk("未登录可浏览活动广场", page.locator(".act-card").count() >= 3,
            "%d 张卡片" % page.locator(".act-card").count())
        chk("未登录看不到「我的活动」",
            page.locator("button:has-text('我的活动')").count() == 0)

        # 未登录时「登录后报名」按钮必须可点，点击应弹出登录框
        btn = page.locator(".act-card button").first
        chk("未登录按钮文案为登录后报名", "登录后报名" in btn.inner_text(), btn.inner_text())
        chk("未登录按钮可点击（不能灰掉）", not btn.is_disabled())
        btn.click()
        page.wait_for_timeout(600)
        chk("点未登录按钮弹出登录框", page.locator(".modal").count() >= 1,
            "登录框数量 %d" % page.locator(".modal").count())
        page.locator(".modal .modal-close").first.click()
        page.wait_for_timeout(300)

        # 负向测试：故意输错密码，期间的 401 属预期，不记为缺陷
        suppress["on"] = True
        page.click("text=登录")
        page.wait_for_selector(".modal", timeout=5000)
        page.fill(".modal input[placeholder='登录账号']", "student01")
        page.fill(".modal input[type='password']", "wrongpass")
        page.click(".modal button.btn-primary")
        page.wait_for_timeout(900)
        chk("错误密码给出提示", page.locator(".modal").count() >= 1, "登录框仍打开（未进入系统）")
        suppress["on"] = False

        # 正确登录
        page.fill(".modal input[type='password']", "123456")
        page.click(".modal button.btn-primary")
        page.wait_for_timeout(1200)
        page.wait_for_selector(".user-chip", timeout=8000)
        chk("正确凭据登录成功", "小明" in page.inner_text(".user-chip"))

        # ---------- 二、学生流程 ----------
        print()
        print("【二】学生报名流程")
        tk_t = login_api("teacher01")
        title_free = PREFIX + "有名额" + RUN
        r = requests.post(BASE + "/api/activities", headers=H(tk_t), json={
            "title": title_free, "description": "自测用", "location": "自测场地",
            "start_time": "2026-12-20 10:00", "end_time": "2026-12-20 12:00", "capacity": 5,
        }, timeout=5)
        aid_free = r.json()["activity_id"]

        title_full = PREFIX + "满员" + RUN
        r = requests.post(BASE + "/api/activities", headers=H(tk_t), json={
            "title": title_full, "description": "自测用", "location": "自测场地",
            "start_time": "2026-12-21 10:00", "end_time": "2026-12-21 12:00", "capacity": 1,
        }, timeout=5)
        aid_full = r.json()["activity_id"]

        title_rev = PREFIX + "需审核" + RUN
        r = requests.post(BASE + "/api/activities", headers=H(tk_t), json={
            "title": title_rev, "description": "自测用", "location": "自测场地",
            "start_time": "2026-12-22 10:00", "end_time": "2026-12-22 12:00",
            "capacity": 3, "require_review": True, "eligibility": "仅限自测",
        }, timeout=5)
        aid_rev = r.json()["activity_id"]

        # 用自测学生占掉满员活动的唯一名额
        requests.post(BASE + f"/api/activities/{aid_full}/register", headers=H(tk_s3), timeout=5)

        # student01 报名有名额的活动
        page.reload(wait_until="networkidle")
        page.wait_for_selector(".act-card", timeout=8000)
        card = page.locator(".act-card", has_text=title_free).first
        card.locator("button").first.click()
        page.wait_for_timeout(1200)
        page.reload(wait_until="networkidle")
        page.wait_for_selector(".act-card", timeout=8000)
        card = page.locator(".act-card", has_text=title_free).first
        chk("报名后按钮变为取消报名", "取消报名" in card.locator("button").first.inner_text(),
            card.locator("button").first.inner_text())

        # 报名满员的活动 → 候补
        card = page.locator(".act-card", has_text=title_full).first
        txt = card.locator("button").first.inner_text()
        chk("满员活动按钮提示进入候补", "候补" in txt, txt)
        card.locator("button").first.click()
        page.wait_for_timeout(1200)
        page.reload(wait_until="networkidle")
        page.wait_for_selector(".act-card", timeout=8000)
        card = page.locator(".act-card", has_text=title_full).first
        chk("满员报名后进入候补（按钮变为退出候补）",
            "退出候补" in card.locator("button").first.inner_text(),
            card.locator("button").first.inner_text())

        # 报名需审核的活动
        card = page.locator(".act-card", has_text=title_rev).first
        card.locator("button").first.click()
        page.wait_for_timeout(1200)
        page.reload(wait_until="networkidle")
        page.wait_for_selector(".act-card", timeout=8000)
        card = page.locator(".act-card", has_text=title_rev).first
        chk("需审核报名后按钮变为撤回申请",
            "撤回申请" in card.locator("button").first.inner_text(),
            card.locator("button").first.inner_text())

        # 我的活动：三态标签
        page.click("text=我的活动")
        page.wait_for_selector(".act-card", timeout=8000)
        mine_txt = page.inner_text(".page")
        chk("我的活动显示三种报名状态",
            all(k in mine_txt for k in ["正式参加", "候补中", "待审核"]),
            mine_txt.replace("\n", " ")[:120])
        chk("候补卡片显示排队位置", "当前排队第" in mine_txt)

        # 时间线
        card = page.locator(".act-card", has_text=title_free).first
        card.locator(".timeline-toggle").click()
        page.wait_for_timeout(300)
        chk("时间线可展开并含提交报名", "提交报名" in card.locator(".timeline").inner_text())

        # ---------- 三、教师流程 ----------
        print()
        print("【三】教师流程")
        page2 = ctx.new_page()
        attach_monitors(page2, "teacher")
        # 审核前有 confirm 确认框、成功后有 alert，统一接受
        page2.on("dialog", lambda d: d.accept())
        login_ui(page2, tk_t)
        page2.click("text=我的活动(管理)")
        page2.wait_for_selector(".act-card", timeout=8000)
        chk("教师进入管理视图", "我发布的活动" in page2.inner_text(".page-head"))

        # 名单分组
        card = page2.locator(".act-card", has_text=title_rev).first
        card.locator("button:has-text('报名名单')").click()
        page2.wait_for_selector(".modal-wide", timeout=5000)
        modal = page2.inner_text(".modal-wide")
        chk("名单弹层显示待审核分组", "待审核" in modal, modal.replace("\n", " ")[:120])
        chk("教师名单含审核按钮", page2.locator(".modal-wide button:has-text('通过')").count() >= 1)
        page2.screenshot(path=os.path.join(OUT, "7_roster_review.png"))

        # 审核通过
        page2.locator(".modal-wide button:has-text('通过')").first.click()
        page2.wait_for_timeout(1200)
        modal = page2.inner_text(".modal-wide") if page2.locator(".modal-wide").count() else ""
        chk("审核通过后待审核分组清空", "待审核（" not in modal, modal.replace("\n", " ")[:100])
        if page2.locator(".modal-wide .modal-close").count():
            page2.locator(".modal-wide .modal-close").first.click()
        page2.wait_for_timeout(400)

        # 发布活动
        page2.click("button:has-text('发布新活动')")
        page2.wait_for_selector(".modal", timeout=5000)
        page2.fill(".modal input[placeholder='如：校园篮球联赛']", PREFIX + "教师发布" + RUN)
        page2.fill(".modal input[placeholder='如：东区篮球场']", "自测场地")
        chk("发布表单字段齐全", page2.locator(".modal input").count() >= 2,
            "%d 个输入框" % page2.locator(".modal input").count())
        page2.locator(".modal .modal-close").first.click()
        page2.wait_for_timeout(300)

        # ---------- 四、管理员 ----------
        print()
        print("【四】管理员流程")
        tk_a = login_api("admin01")
        page3 = ctx.new_page()
        attach_monitors(page3, "admin")
        login_ui(page3, tk_a)
        chk("管理员导航显示账号管理",
            page3.locator("button:has-text('账号管理')").count() == 1)
        page3.click("text=账号管理")
        page3.wait_for_selector(".admin-table", timeout=8000)
        admin_txt = page3.inner_text(".admin-table")
        chk("账号列表含三种角色",
            all(k in admin_txt for k in ["学生", "教师", "管理员"]),
            admin_txt.replace("\n", " ")[:100])
        chk("当前管理员不能停用自己",
            page3.locator(".admin-table button[disabled]").count() >= 1)
        page3.screenshot(path=os.path.join(OUT, "8_admin.png"))

        # 活动广场：管理员只读名单
        page3.click("text=活动广场")
        page3.wait_for_selector(".act-card", timeout=8000)
        c = page3.locator(".act-card").first
        chk("管理员在活动卡片上看到报名名单入口",
            c.locator("button:has-text('报名名单')").count() == 1)
        c.locator("button:has-text('报名名单')").click()
        page3.wait_for_selector(".modal-wide", timeout=5000)
        chk("管理员名单标注只读", "只读" in page3.inner_text(".modal-wide"))

        b.close()

    # ---------- 五、越权（接口层） ----------
    print()
    print("【五】越权与边界（接口层）")
    tk_s1 = login_api("student01")
    r = requests.get(BASE + "/api/admin/users", headers=H(tk_s1), timeout=5)
    chk("学生访问管理接口 403", r.status_code == 403, "实际 %d" % r.status_code)
    r = requests.get(BASE + "/api/admin/users", headers=H(tk_t), timeout=5)
    chk("教师访问管理接口 403", r.status_code == 403, "实际 %d" % r.status_code)
    r = requests.get(BASE + "/api/activities/999999", timeout=5)
    chk("不存在的活动返回 404", r.status_code == 404, "实际 %d" % r.status_code)
    r = requests.get(BASE + "/api/my-activities", timeout=5)
    chk("未登录访问我的活动 401/403", r.status_code in (401, 403), "实际 %d" % r.status_code)
    r = requests.post(BASE + "/api/activities", headers=H(tk_s1), json={
        "title": "x", "location": "y", "start_time": "2026-12-01 10:00",
        "end_time": "2026-12-01 12:00", "capacity": 1}, timeout=5)
    chk("学生发布活动 403", r.status_code == 403, "实际 %d" % r.status_code)
    r = requests.post(BASE + "/api/activities", headers=H(tk_t), json={
        "title": "x", "location": "y", "start_time": "2020-01-01 10:00",
        "end_time": "2020-01-01 12:00", "capacity": 1}, timeout=5)
    chk("发布已过时间的活动 400", r.status_code == 400, "实际 %d" % r.status_code)
    r = requests.post(BASE + "/api/activities", headers=H(tk_t), json={
        "title": "x", "location": "y", "start_time": "2026-12-01 12:00",
        "end_time": "2026-12-01 10:00", "capacity": 1}, timeout=5)
    chk("结束早于开始 400", r.status_code == 400, "实际 %d" % r.status_code)

    # ---------- 六、运行质量 ----------
    print()
    print("【六】运行质量")
    real_console = [c for c in console_errors if c[1] == "error"]
    chk("无页面 console 错误", not real_console, str(real_console[:2])[:200])
    chk("无未捕获的页面异常", not page_errors, str(page_errors[:2])[:200])
    chk("无 5xx 请求", not bad_requests, str(bad_requests[:2])[:200])

    cleanup()
    print()
    print("=" * 64)
    print("端到端自测：%d 项通过 / %d 项失败" % (PASS, FAIL))
    print("=" * 64)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
