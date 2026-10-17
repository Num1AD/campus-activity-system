# -*- coding: utf-8 -*-
"""
_shot_demo.py —— 用演示数据拍一张 V3.0 界面截图（供报告与交付核对）

流程：教师审核 student01 的待审核报名 → 学生登录后看到未读徽标与时间线。
只读取与一次审核操作，不新增活动，保持演示数据整洁。
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


def login(u, p="123456"):
    return requests.post(BASE + "/api/login", json={"username": u, "password": p},
                         timeout=5).json()["token"]


def main():
    for _ in range(30):
        try:
            requests.get(BASE + "/api/health", timeout=2)
            break
        except Exception:
            time.sleep(1)

    tk_t = login("teacher01")
    tk_s1 = login("student01")
    H = lambda t: {"Authorization": "Bearer " + t}

    # 学生先标记已读，保证随后的审核一定算未读
    requests.post(BASE + "/api/my-registration-events/read", headers=H(tk_s1), timeout=5)

    # 教师审核 student01 在「人工智能前沿讲座」的待审核报名
    acts = requests.get(BASE + "/api/activities", timeout=5).json()["activities"]
    act = next(a for a in acts if a["title"] == "人工智能前沿讲座")
    r = requests.get(BASE + f"/api/activities/{act['id']}/registrations", headers=H(tk_t), timeout=5)
    pend = [s for s in r.json()["students"] if s["reg_status"] == "pending"]
    if pend:
        requests.post(BASE + f"/api/activities/{act['id']}/registrations/{pend[0]['id']}/review",
                      headers=H(tk_t), json={"approve": True}, timeout=5)
        print("已审核通过 1 条待审核报名")

    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        ctx = b.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.goto(BASE, wait_until="networkidle")
        page.evaluate("t => localStorage.setItem('cas_token', t)", tk_s1)
        page.reload(wait_until="networkidle")
        page.wait_for_selector(".act-card", timeout=8000)
        page.screenshot(path=os.path.join(OUT, "5_plaza_with_badge.png"))
        print("已截图：活动广场（含未读徽标）")

        page.click("text=我的活动")
        page.wait_for_selector(".timeline-toggle", timeout=8000)
        # 展开「人工智能前沿讲座」的时间线
        card = page.locator(".act-card", has_text="人工智能前沿讲座").first
        card.locator(".timeline-toggle").click()
        page.wait_for_timeout(400)
        page.screenshot(path=os.path.join(OUT, "6_mine_timeline.png"))
        print("已截图：我的活动（时间线展开）")
        b.close()


if __name__ == "__main__":
    main()
