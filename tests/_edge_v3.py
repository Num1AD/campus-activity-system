# -*- coding: utf-8 -*-
"""
_edge_v3.py —— 边界与长内容自测

补测一些正常流程之外、但真实使用中会遇到的情形：
  1. 超长标题与描述：卡片是否撑破、是否影响同行卡片
  2. 教师编辑活动：标题与容量修改是否生效，界面是否同步
  3. 教师取消活动：学生端是否变为「已取消 / 不可报名」
  4. 审核拒绝：学生时间线是否出现「报名未通过」，按钮是否回到可报名
  5. 活动满员后容量上调：候补者不自动递补（规则一致性检查）
  6. 同一学生跨多个活动的状态互不串扰
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
PREFIX = "【边界】"
RUN = str(int(time.time()))[-5:]

PASS = FAIL = 0
console_err = []


def chk(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  " + detail) if detail else ""))
    else:
        FAIL += 1
        print("  [FAIL] %s  %s" % (name, detail))


def login_api(u, p="123456"):
    return requests.post(BASE + "/api/login", json={"username": u, "password": p},
                         timeout=5).json()["token"]


def H(t):
    return {"Authorization": "Bearer " + t}


def mk(tk, title, cap, review=False, day=25):
    r = requests.post(BASE + "/api/activities", headers=H(tk), json={
        "title": title, "description": "边界自测", "location": "边界场地",
        "start_time": "2026-12-%02d 10:00" % day, "end_time": "2026-12-%02d 12:00" % day,
        "capacity": cap, "require_review": review, "eligibility": "",
    }, timeout=5)
    assert r.status_code == 200, r.text
    return r.json()["activity_id"]


def cleanup():
    tk = login_api("teacher01")
    acts = requests.get(BASE + "/api/activities", timeout=5).json()["activities"]
    old = [a["id"] for a in acts if a["title"].startswith(PREFIX)]
    import sqlite3
    db = sqlite3.connect(os.path.join("backend", "activity.db"))
    try:
        if old:
            q = ",".join("?" * len(old))
            db.execute("DELETE FROM registration_events WHERE activity_id IN (%s)" % q, old)
            db.execute("DELETE FROM registrations WHERE activity_id IN (%s)" % q, old)
            db.execute("DELETE FROM activities WHERE id IN (%s)" % q, old)
            db.commit()
    finally:
        db.close()
    return len(old)


def main():
    removed = cleanup()
    print("已清理上轮边界活动 %d 个\n" % removed)

    tk_t = login_api("teacher01")
    tk_s1 = login_api("student01")
    tk_s2 = login_api("student02")

    print("【1】超长标题与描述")
    long_title = PREFIX + "超长标题" + RUN + "这是一个用于测试卡片在标题很长时是否会被撑破的活动名称"
    long_desc = "描述" * 80
    r = requests.post(BASE + "/api/activities", headers=H(tk_t), json={
        "title": long_title[:64], "description": long_desc, "location": "边界场地" * 8,
        "start_time": "2026-12-26 10:00", "end_time": "2026-12-26 12:00", "capacity": 10,
    }, timeout=5)
    aid_long = r.json()["activity_id"]
    chk("超长内容活动创建成功", r.status_code == 200, r.text[:80])

    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        ctx = b.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.on("console", lambda m: console_err.append(m.text) if m.type == "error" else None)
        page.on("dialog", lambda d: d.accept())
        page.goto(BASE, wait_until="networkidle")
        page.evaluate("t => localStorage.setItem('cas_token', t)", tk_s1)
        page.reload(wait_until="networkidle")
        page.wait_for_selector(".act-card", timeout=8000)

        card = page.locator(".act-card", has_text="超长标题" + RUN).first
        page.wait_for_timeout(300)
        box = card.bounding_box()
        vw = page.evaluate("window.innerWidth")
        chk("长内容卡片不超出视口",
            box and box["x"] >= 0 and box["x"] + box["width"] <= vw + 1,
            "x=%.0f 宽=%.0f" % (box["x"], box["width"]) if box else "未取到")
        r2 = page.evaluate("""() => ({
            scrollW: document.documentElement.scrollWidth,
            vw: window.innerWidth })""")
        chk("长内容页面无横向滚动",
            r2["scrollW"] <= r2["vw"] + 1,
            "scrollWidth=%d vw=%d" % (r2["scrollW"], r2["vw"]))
        # 卡片标题不能无限撑高：同一行其他卡片不应被拉到离谱高度
        heights = page.evaluate("""() => Array.from(document.querySelectorAll('.act-card'))
            .slice(0, 3).map(e => Math.round(e.getBoundingClientRect().height))""")
        chk("同行卡片高度一致（长标题不破坏对齐）", len(set(heights)) == 1, str(heights))
        page.screenshot(path=os.path.join(OUT, "9_long_content.png"))

        print()
        print("【2】教师编辑活动")
        page2 = ctx.new_page()
        page2.on("dialog", lambda d: d.accept())
        page2.goto(BASE, wait_until="networkidle")
        page2.evaluate("t => localStorage.setItem('cas_token', t)", tk_t)
        page2.reload(wait_until="networkidle")
        page2.wait_for_selector(".act-card", timeout=8000)
        page2.click("text=我的活动(管理)")
        page2.wait_for_selector(".act-card", timeout=8000)
        c = page2.locator(".act-card", has_text="超长标题" + RUN).first
        c.locator("button:has-text('编辑')").click()
        page2.wait_for_selector(".modal", timeout=5000)
        # 编辑弹层的输入框没有 placeholder，按顺序取：第一个是活动名称
        chk("编辑弹层预填了原名称",
            (RUN + "这是一个") in page2.locator(".modal input").first.input_value(),
            page2.locator(".modal input").first.input_value()[:40])
        page2.locator(".modal input").first.fill(PREFIX + "已改名" + RUN)
        page2.locator(".modal button.btn-primary").first.click()
        page2.wait_for_timeout(1200)
        chk("编辑后标题已更新",
            page2.locator(".act-card", has_text="已改名" + RUN).count() >= 1)

        print()
        print("【3】教师取消活动")
        aid_cancel = mk(tk_t, PREFIX + "待取消" + RUN, 5, day=27)
        requests.delete(BASE + f"/api/activities/{aid_cancel}/cancel", headers=H(tk_s1), timeout=5)
        requests.post(BASE + f"/api/activities/{aid_cancel}/cancel", headers=H(tk_t), timeout=5)
        page3 = ctx.new_page()
        page3.on("console", lambda m: console_err.append(m.text) if m.type == "error" else None)
        page3.goto(BASE, wait_until="networkidle")
        page3.evaluate("t => localStorage.setItem('cas_token', t)", tk_s1)
        page3.reload(wait_until="networkidle")
        page3.wait_for_selector(".act-card", timeout=8000)
        c = page3.locator(".act-card", has_text="待取消" + RUN).first
        chk("学生端显示已取消", "已取消" in c.inner_text(), c.inner_text().replace("\n", " ")[:80])
        chk("已取消活动按钮为不可报名", "不可报名" in c.locator("button").first.inner_text(),
            c.locator("button").first.inner_text())

        print()
        print("【4】审核拒绝")
        aid_rej = mk(tk_t, PREFIX + "待拒绝" + RUN, 3, review=True, day=28)
        requests.post(BASE + f"/api/activities/{aid_rej}/register", headers=H(tk_s1), timeout=5)
        r = requests.get(BASE + f"/api/activities/{aid_rej}/registrations", headers=H(tk_t), timeout=5)
        sid = [s for s in r.json()["students"] if s["reg_status"] == "pending"][0]["id"]
        requests.post(BASE + f"/api/activities/{aid_rej}/registrations/{sid}/review",
                      headers=H(tk_t), json={"approve": False}, timeout=5)
        ev = requests.get(BASE + "/api/my-registration-events", headers=H(tk_s1), timeout=5).json()
        mine = [e for e in ev["events"] if e["activity_id"] == aid_rej]
        chk("被拒后时间线出现「报名未通过」",
            any(e["to_status_text"] == "报名未通过" for e in mine),
            str([e["to_status_text"] for e in mine]))
        page3.reload(wait_until="networkidle")
        page3.wait_for_selector(".act-card", timeout=8000)
        c = page3.locator(".act-card", has_text="待拒绝" + RUN).first
        chk("被拒后按钮回到可报名", "报名" in c.locator("button").first.inner_text()
            and "撤回" not in c.locator("button").first.inner_text(),
            c.locator("button").first.inner_text())

        # 被拒的记录已删除，卡片不再存在；必须在「已结束的报名」里能看到结果
        page3.click("text=我的活动")
        page3.wait_for_selector(".page", timeout=8000)
        page3.wait_for_timeout(500)
        panel = page3.locator(".ended-panel")
        chk("我的活动出现「已结束的报名」区块", panel.count() == 1, "%d 个" % panel.count())
        if panel.count():
            ptxt = panel.first.inner_text()
            chk("该区块说明被拒的活动与结果",
                ("待拒绝" + RUN) in ptxt and "报名未通过" in ptxt,
                ptxt.replace("\n", " | ")[:120])
        page3.screenshot(path=os.path.join(OUT, "10_ended_panel.png"))

        print()
        print("【5】满员后上调容量")
        aid_cap = mk(tk_t, PREFIX + "容量调整" + RUN, 1, day=29)
        requests.post(BASE + f"/api/activities/{aid_cap}/register", headers=H(tk_s1), timeout=5)
        r = requests.post(BASE + f"/api/activities/{aid_cap}/register", headers=H(tk_s2), timeout=5)
        chk("容量 1 时第二人进候补", r.json()["reg_status"] == "候补中", str(r.json())[:80])
        r = requests.put(BASE + f"/api/activities/{aid_cap}", headers=H(tk_t), json={
            "title": PREFIX + "容量调整" + RUN, "description": "边界自测", "location": "边界场地",
            "start_time": "2026-12-29 10:00", "end_time": "2026-12-29 12:00",
            "capacity": 3}, timeout=5)
        chk("容量上调成功", r.status_code == 200, r.text[:80])
        mine2 = requests.get(BASE + "/api/my-activities", headers=H(tk_s2), timeout=5).json()["activities"]
        item = [a for a in mine2 if a["id"] == aid_cap][0]
        chk("上调容量后候补者不被自动递补（需等取消触发）",
            item["reg_status_code"] == "waitlisted",
            "当前状态 %s" % item["reg_status"])

        print()
        print("【6】跨活动状态互不串扰")
        aid_a = mk(tk_t, PREFIX + "活动甲" + RUN, 5, day=30)
        aid_b = mk(tk_t, PREFIX + "活动乙" + RUN, 1, day=30)
        requests.post(BASE + f"/api/activities/{aid_a}/register", headers=H(tk_s1), timeout=5)
        requests.post(BASE + f"/api/activities/{aid_b}/register", headers=H(tk_s2), timeout=5)
        requests.post(BASE + f"/api/activities/{aid_b}/register", headers=H(tk_s1), timeout=5)
        mine3 = requests.get(BASE + "/api/my-activities", headers=H(tk_s1), timeout=5).json()["activities"]
        a_ = [x for x in mine3 if x["id"] == aid_a][0]
        b_ = [x for x in mine3 if x["id"] == aid_b][0]
        chk("同一学生在不同活动上的状态各自独立",
            a_["reg_status_code"] == "confirmed" and b_["reg_status_code"] == "waitlisted",
            "甲=%s 乙=%s" % (a_["reg_status"], b_["reg_status"]))

        b.close()

    chk("边界测试期间无 console 错误", not console_err, str(console_err[:2])[:150])
    cleanup()
    print()
    print("=" * 62)
    print("边界自测：%d 项通过 / %d 项失败" % (PASS, FAIL))
    print("=" * 62)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
