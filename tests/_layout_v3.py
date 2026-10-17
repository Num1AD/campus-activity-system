# -*- coding: utf-8 -*-
"""
_layout_v3.py —— 桌面分辨率布局检查

范围说明：任务说明未要求移动端适配，因此只检查桌面常见分辨率
（1920×1080 / 1600×900 / 1440×900 / 1366×768 / 1280×800 / 1024×768）。
移动端宽度不作为本轮验收条件，仅在结论里如实标注为已知限制。

每个分辨率下逐个视图检查：
  1. 是否出现横向溢出（scrollWidth 超过视口宽度）
  2. 是否有元素越出视口左右边界（错位 / 溢出）
  3. 顶栏三个区域（品牌 / 导航 / 用户区）是否重叠
  4. 弹层是否完整落在视口内

视图：活动广场 / 我的活动（学生，含时间线展开）/ 我的活动（教师）/ 账号管理 / 报名名单弹层
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

VIEWPORTS = [
    (1920, 1080, "1920×1080 桌面大屏"),
    (1600, 900, "1600×900 笔记本"),
    (1440, 900, "1440×900 MacBook"),
    (1366, 768, "1366×768 常见笔记本"),
    (1280, 800, "1280×800 小笔记本"),
    (1024, 768, "1024×768 老式屏"),
]

PASS = FAIL = 0
issues = []


def chk(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("    [PASS] %s%s" % (name, ("  " + detail) if detail else ""))
    else:
        FAIL += 1
        issues.append((name, detail))
        print("    [FAIL] %s  %s" % (name, detail))


def login_api(u, p="123456"):
    return requests.post(BASE + "/api/login", json={"username": u, "password": p},
                         timeout=5).json()["token"]


def wait_ready():
    for _ in range(30):
        try:
            requests.get(BASE + "/api/health", timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False


OVERFLOW_JS = """
() => {
  const w = window.innerWidth;
  const bad = [];
  const skip = new Set(['SCRIPT', 'STYLE', 'LINK', 'META', 'HEAD', 'TITLE']);
  document.querySelectorAll('body *').forEach(el => {
    if (skip.has(el.tagName)) return;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return;
    if (r.right > w + 1.5 || r.left < -1.5) {
      bad.push({
        tag: el.tagName,
        cls: (el.className || '').toString().slice(0, 46),
        left: Math.round(r.left),
        right: Math.round(r.right),
        w: Math.round(r.width)
      });
    }
  });
  return {
    vw: w,
    scrollW: document.documentElement.scrollWidth,
    clientW: document.documentElement.clientWidth,
    bad: bad.slice(0, 10)
  };
}
"""

OVERLAP_JS = """
() => {
  // 顶栏三块区域是否互相重叠
  const pick = sel => { const e = document.querySelector(sel); return e ? e.getBoundingClientRect() : null; };
  const brand = pick('.brand'), nav = pick('.nav'), user = pick('.user-area');
  const overlap = (a, b) => !!(a && b && a.left < b.right - 1 && b.left < a.right - 1
                              && a.top < b.bottom - 1 && b.top < a.bottom - 1);
  return {
    brandNav: overlap(brand, nav),
    navUser: overlap(nav, user),
    brandUser: overlap(brand, user),
    navRight: nav ? Math.round(nav.right) : null,
    userRight: user ? Math.round(user.right) : null
  };
}
"""


def check_page(page, label, vw):
    r = page.evaluate(OVERFLOW_JS)
    chk("%s：无横向溢出" % label, r["scrollW"] <= r["vw"] + 1,
        "scrollWidth=%d 视口=%d" % (r["scrollW"], r["vw"]))
    chk("%s：无元素越界" % label, not r["bad"], str(r["bad"][:3]))
    o = page.evaluate(OVERLAP_JS)
    chk("%s：顶栏不重叠" % label,
        not (o["brandNav"] or o["navUser"] or o["brandUser"]),
        "brand-nav=%s nav-user=%s" % (o["brandNav"], o["navUser"]))


def main():
    if not wait_ready():
        print("服务未就绪")
        return 1

    tk_s = login_api("student01")
    tk_t = login_api("teacher01")
    tk_a = login_api("admin01")

    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        for w, h, label in VIEWPORTS:
            print()
            print("【%s】" % label)
            ctx = b.new_context(viewport={"width": w, "height": h})

            # --- 活动广场（未登录） ---
            page = ctx.new_page()
            page.goto(BASE, wait_until="networkidle")
            page.wait_for_selector(".act-card", timeout=8000)
            check_page(page, "活动广场", w)
            page.screenshot(path=os.path.join(OUT, "layout_%dx%d_list.png" % (w, h)))

            # --- 我的活动（学生，时间线展开） ---
            page.evaluate("t => localStorage.setItem('cas_token', t)", tk_s)
            page.reload(wait_until="networkidle")
            page.wait_for_selector(".act-card", timeout=8000)
            page.click("text=我的活动")
            page.wait_for_selector(".act-card", timeout=8000)
            # 展开第一个时间线，检查展开后是否溢出
            if page.locator(".timeline-toggle").count():
                page.locator(".timeline-toggle").first.click()
                page.wait_for_timeout(300)
            check_page(page, "我的活动(学生)", w)
            page.screenshot(path=os.path.join(OUT, "layout_%dx%d_mine.png" % (w, h)))
            page.close()

            # --- 教师视图 + 名单弹层 ---
            page2 = ctx.new_page()
            page2.on("dialog", lambda d: d.accept())
            page2.goto(BASE, wait_until="networkidle")
            page2.evaluate("t => localStorage.setItem('cas_token', t)", tk_t)
            page2.reload(wait_until="networkidle")
            page2.wait_for_selector(".act-card", timeout=8000)
            page2.click("text=我的活动(管理)")
            page2.wait_for_selector(".act-card", timeout=8000)
            check_page(page2, "我的活动(教师)", w)

            btn = page2.locator("button:has-text('报名名单')")
            if btn.count():
                btn.first.click()
                page2.wait_for_selector(".modal-wide", timeout=5000)
                box = page2.locator(".modal-wide").bounding_box()
                chk("名单弹层完整在视口内",
                    box and box["x"] >= -1 and box["x"] + box["width"] <= w + 1,
                    "x=%.0f 宽=%.0f 视口=%d" % (box["x"], box["width"], w) if box else "未取到尺寸")
                r = page2.evaluate(OVERFLOW_JS)
                chk("名单弹层无横向溢出", r["scrollW"] <= r["vw"] + 1,
                    "scrollWidth=%d" % r["scrollW"])
            page2.close()

            # --- 管理员账号管理 ---
            page3 = ctx.new_page()
            page3.goto(BASE, wait_until="networkidle")
            page3.evaluate("t => localStorage.setItem('cas_token', t)", tk_a)
            page3.reload(wait_until="networkidle")
            page3.wait_for_selector(".act-card", timeout=8000)
            page3.click("text=账号管理")
            page3.wait_for_selector(".admin-table", timeout=8000)
            check_page(page3, "账号管理", w)
            page3.screenshot(path=os.path.join(OUT, "layout_%dx%d_admin.png" % (w, h)))
            page3.close()
            ctx.close()

        b.close()

    print()
    print("=" * 64)
    print("布局检查：%d 项通过 / %d 项失败" % (PASS, FAIL))
    if issues:
        print("失败项：")
        for n, d in issues:
            print("  - %s  %s" % (n, d))
    print("=" * 64)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
