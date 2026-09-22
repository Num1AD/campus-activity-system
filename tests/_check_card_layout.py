"""
_check_card_layout.py —— 卡片对齐效果检查（截图对比）

用于核验活动卡片在"有/无参加资格说明"混排时是否等高、底部操作区是否对齐。
"""

import os
import sys

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8000"
OUT = os.path.join("report", "_v2check")
os.makedirs(OUT, exist_ok=True)


with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
    pg = ctx.new_page()
    pg.on("dialog", lambda d: d.accept())

    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_timeout(800)

    # 以学生身份登录（复现反馈截图：部分活动显示"撤回申请 / 取消报名"）
    pg.click('.user-area button:has-text("登录")')
    pg.wait_for_timeout(400)
    pg.fill('input[placeholder="登录账号"]', "student01")
    pg.fill('.modal input[type="password"]', "123456")
    pg.click('.modal button[type="submit"]')
    pg.wait_for_timeout(1500)

    # 量测前把鼠标移开：卡片有 :hover { transform: translateY(-2px) }，
    # 登录时最后点击的按钮位置可能正落在某张卡片上，会造成 2px 的测量干扰
    pg.mouse.move(2, 2)
    pg.wait_for_timeout(300)

    # 量测每张卡片的几何信息
    boxes = pg.eval_on_selector_all(
        ".act-card",
        "els => els.map(e => {"
        "  const r = e.getBoundingClientRect();"
        "  const meta = e.querySelector('.act-meta');"
        "  const foot = e.querySelector('.act-foot');"
        "  const mr = meta ? meta.getBoundingClientRect() : null;"
        "  const fr = foot ? foot.getBoundingClientRect() : null;"
        "  return {title: e.querySelector('.act-title').innerText,"
        "          top: Math.round(r.top), h: Math.round(r.height),"
        "          metaTop: mr ? Math.round(mr.top) : null,"
        "          footTop: fr ? Math.round(fr.top) : null,"
        "          footBottom: fr ? Math.round(fr.bottom) : null};"
        "})",
    )
    print("=== 卡片几何（视口坐标）===")
    for i, bx in enumerate(boxes, 1):
        print(f"  {i}. {bx['title'][:16]:<18} 卡片 top={bx['top']:>4} 高={bx['h']:>4} "
              f"时间行 top={bx['metaTop']:>4} 操作区 top={bx['footTop']:>4} 底={bx['footBottom']:>4}")

    # 按行分组（top 相近视为同一行），检查同行底部是否对齐
    print()
    print("=== 同行对齐检查 ===")
    groups = {}
    for bx in boxes:
        key = round(bx["top"] / 20)
        groups.setdefault(key, []).append(bx)
    ok = True
    for key, g in sorted(groups.items()):
        if len(g) < 2:
            continue
        heights = {x["h"] for x in g}
        metas = {x["metaTop"] for x in g}
        foots = {x["footBottom"] for x in g}
        same_h = len(heights) == 1
        same_m = len(metas) == 1
        same_f = len(foots) == 1
        if not (same_h and same_m and same_f):
            ok = False
        print(f"  行（top≈{g[0]['top']}，{len(g)} 张）：")
        print(f"     卡片高度 {sorted(heights)} {'一致 ✔' if same_h else '不一致 ✘'}")
        print(f"     时间行   {sorted(metas)} {'对齐 ✔' if same_m else '未对齐 ✘'}")
        print(f"     操作区底 {sorted(foots)} {'对齐 ✔' if same_f else '未对齐 ✘'}")
    print()
    print("结论:", "同行卡片等高，时间行与操作区均对齐 ✔" if ok else "仍有未对齐项，需继续调整 ✘")

    pg.screenshot(path=f"{OUT}/7_card_layout.png", full_page=False)
    pg.locator(".card-grid").first.screenshot(path=f"{OUT}/8_card_grid.png")
    print("截图:", f"{OUT}/7_card_layout.png", "|", f"{OUT}/8_card_grid.png")

    b.close()
