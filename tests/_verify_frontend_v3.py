# -*- coding: utf-8 -*-
"""
_verify_frontend_v3.py —— V3.0 前端交互实测（playwright + 系统 Edge 无头模式）

验证点：
1. 未读徽标：教师操作产生提醒后，学生导航栏出现未读数（R3-01）
2. 进入"我的活动"后徽标清零（R3-01）
3. 状态变化时间线可展开，且包含教师审核这一步（R3-01）
4. 候补卡片显示排队位置（R3-01）
5. 提交期间按钮禁用并显示"处理中…"，连点不会发出第二次请求（R3-02）

截图输出到 report/_v3check/
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
PREFIX = "【V3前端】"
# 每轮活动标题带唯一后缀：上一轮的活动虽已取消，但记录仍在列表里，
# 同名会让选择器抓到旧卡片（旧卡片上学生已报名，按钮变成"取消报名"）
RUN = str(int(time.time()))[-5:]

PASS = FAIL = 0


def chk(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  " + detail) if detail else ""))
    else:
        FAIL += 1
        print("  [FAIL] %s  %s" % (name, detail))


def api_login(u, p="123456"):
    r = requests.post(BASE + "/api/login", json={"username": u, "password": p}, timeout=5)
    return r.json()["token"]


def H(tk):
    return {"Authorization": "Bearer " + tk}


def prepare():
    """准备三件事：① 学生 1 有一条待审核报名；② 教师审核通过它产生提醒；③ 一个可报名的新活动。"""
    tk_t = api_login("teacher01")
    tk_s1 = api_login("student01")

    # 清理上一轮
    acts = requests.get(BASE + "/api/activities", timeout=5).json()["activities"]
    for a in acts:
        if a["title"].startswith(PREFIX):
            requests.post(BASE + f"/api/activities/{a['id']}/cancel", headers=H(tk_t), timeout=5)

    # ① 建一个需审核的活动，学生 1 报名 → 待审核
    title_review = PREFIX + "审核提醒验证" + RUN
    r = requests.post(BASE + "/api/activities", headers=H(tk_t), json={
        "title": title_review,
        "description": "用于验证未读徽标与时间线",
        "location": "自动验证场地",
        "start_time": "2026-12-28 10:00", "end_time": "2026-12-28 12:00",
        "capacity": 3, "require_review": True, "eligibility": "",
    }, timeout=5)
    aid_review = r.json()["activity_id"]
    requests.post(BASE + f"/api/activities/{aid_review}/register", headers=H(tk_s1), timeout=5)

    # 先把已读游标清零，确保下一步的审核一定算未读
    requests.post(BASE + "/api/my-registration-events/read", headers=H(tk_s1), timeout=5)

    # ② 教师审核通过 → 产生 needs_notice 事件
    r = requests.get(BASE + f"/api/activities/{aid_review}/registrations", headers=H(tk_t), timeout=5)
    stu = [s for s in r.json()["students"] if s["reg_status"] == "pending"]
    sid = stu[0]["id"]
    requests.post(
        BASE + f"/api/activities/{aid_review}/registrations/{sid}/review",
        headers=H(tk_t), json={"approve": True}, timeout=5,
    )

    # ③ 一个无需审核、还有名额的活动，用于测试在途禁用
    title_reg = PREFIX + "提交保护验证" + RUN
    r = requests.post(BASE + "/api/activities", headers=H(tk_t), json={
        "title": title_reg,
        "description": "用于验证提交期间按钮禁用",
        "location": "自动验证场地",
        "start_time": "2026-12-29 10:00", "end_time": "2026-12-29 12:00",
        "capacity": 5,
    }, timeout=5)
    aid_reg = r.json()["activity_id"]
    return aid_review, aid_reg, title_review, title_reg


def main():
    aid_review, aid_reg, title_review, title_reg = prepare()
    tk_s1 = api_login("student01")
    tk_s2 = api_login("student02")

    unread = requests.get(BASE + "/api/my-registration-events",
                          headers=H(tk_s1), timeout=5).json()["unread_count"]
    print("准备完成：学生1 未读 %d 条，可报名活动 id=%d\n" % (unread, aid_reg))

    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        ctx = b.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()

        # ---------- 1. 未读徽标 ----------
        print("【1】未读徽标")
        page.goto(BASE, wait_until="networkidle")
        page.evaluate("t => localStorage.setItem('cas_token', t)", tk_s1)
        page.reload(wait_until="networkidle")
        page.wait_for_selector(".nav-badge", timeout=8000)
        badge = page.inner_text(".nav-badge")
        chk("导航栏显示未读徽标", badge.strip() == str(unread), "徽标=%s 期望=%d" % (badge, unread))
        page.screenshot(path=os.path.join(OUT, "1_nav_badge.png"))

        # ---------- 2. 进入我的活动后清零 ----------
        print()
        print("【2】进入我的活动后徽标清零")
        page.click("text=我的活动")
        page.wait_for_selector(".timeline-toggle", timeout=8000)
        page.wait_for_timeout(600)
        chk("徽标消失", page.locator(".nav-badge").count() == 0,
            "仍存在 %d 个" % page.locator(".nav-badge").count())

        # ---------- 3. 状态变化时间线 ----------
        print()
        print("【3】状态变化时间线")
        toggles = page.locator(".timeline-toggle")
        chk("时间线入口存在", toggles.count() >= 1, "%d 个" % toggles.count())
        # 定位到"审核提醒验证"这张卡片，否则展开的可能是别的活动
        target_card = page.locator(".act-card", has_text=title_review).first
        target_card.locator(".timeline-toggle").click()
        page.wait_for_timeout(300)
        txt = target_card.locator(".timeline").inner_text()
        chk("时间线含「提交报名」", "提交报名" in txt, txt.replace("\n", " | ")[:100])
        chk("时间线含「教师审核通过」", "教师审核通过" in txt, txt.replace("\n", " | ")[:100])
        page.screenshot(path=os.path.join(OUT, "2_timeline.png"))

        # ---------- 4. 候补排队位置 ----------
        print()
        print("【4】候补排队位置")
        page2 = ctx.new_page()
        page2.goto(BASE, wait_until="networkidle")
        page2.evaluate("t => localStorage.setItem('cas_token', t)", tk_s2)
        page2.reload(wait_until="networkidle")
        page2.click("text=我的活动")
        page2.wait_for_selector(".act-card", timeout=8000)
        hint = page2.locator(".queue-hint")
        chk("候补卡片显示排队位置", hint.count() >= 1, "%d 个" % hint.count())
        if hint.count():
            t = hint.first.inner_text()
            chk("排队文案含位次与总人数", "第" in t and "位" in t and "候补" in t, t)
        page2.screenshot(path=os.path.join(OUT, "3_queue_position.png"))
        page2.close()

        # ---------- 5. 提交在途禁用 ----------
        print()
        print("【5】提交期间按钮禁用（R3-02）")
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_selector(".act-card", timeout=8000)

        # 用 CDP 加 600ms 网络延迟，让"在途"这段可以被观察到
        cdp = ctx.new_cdp_session(page)
        cdp.send("Network.enable")
        cdp.send("Network.emulateNetworkConditions", {
            "offline": False, "latency": 600,
            "downloadThroughput": -1, "uploadThroughput": -1,
        })

        card = page.locator(".act-card", has_text=title_reg).first
        card.scroll_into_view_if_needed()
        btn = card.locator("button").first
        before = btn.inner_text().strip()
        chk("初始按钮可点（文案为报名）", "报名" in before, before)

        reqs = []
        page.on("request", lambda r: reqs.append(r.url) if "/register" in r.url and r.method == "POST" else None)

        btn.click()
        page.wait_for_timeout(160)
        during_text = btn.inner_text().strip()
        during_disabled = btn.is_disabled()
        chk("在途期间按钮禁用", during_disabled, "disabled=%s" % during_disabled)
        chk("在途期间文案变为处理中", "处理中" in during_text, during_text)

        # 在途期间再点两次（模拟连点），应被忽略
        try:
            btn.click(timeout=500, force=True)
            btn.click(timeout=500, force=True)
        except Exception:
            pass
        page.wait_for_timeout(1600)
        chk("连点未产生第二次请求", len(reqs) == 1, "实际 %d 次" % len(reqs))
        page.screenshot(path=os.path.join(OUT, "4_inflight.png"))

        b.close()

    # 清理
    tk_t = api_login("teacher01")
    acts = requests.get(BASE + "/api/activities", timeout=5).json()["activities"]
    for a in acts:
        if a["title"].startswith(PREFIX):
            requests.post(BASE + f"/api/activities/{a['id']}/cancel", headers=H(tk_t), timeout=5)

    print()
    print("=" * 62)
    print("V3.0 前端实测：%d 项通过 / %d 项失败" % (PASS, FAIL))
    print("=" * 62)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
