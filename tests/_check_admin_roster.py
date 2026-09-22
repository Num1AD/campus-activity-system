"""
_check_admin_roster.py —— 验证管理员的报名与候补名单「只读查看」前端表现（playwright + 系统 Edge 无头）

验证点：
1. 管理员在活动广场能看到「报名名单」入口（此前只显示一行灰色文字）
2. 名单弹层标题带「（只读）」标记
3. 弹层内不出现「通过 / 拒绝」按钮 —— 管理员不处理审核
4. 待审核分组下方显示「审核由组织该活动的教师处理」的说明
5. 教师打开同一名单时审核按钮仍在（确认没有误伤教师端）

脚本会自行准备一条待审核报名，可重复运行。
截图输出到 report/_v2check/
"""

import os
import sys

import requests
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8000"
OUT = os.path.join("report", "_v2check")
os.makedirs(OUT, exist_ok=True)
TARGET = "人工智能前沿讲座"   # 演示数据中设置为「需要审核」的活动

PASS = FAIL = 0


def chk(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def prepare_pending():
    """确保目标活动存在一条待审核报名（脚本含只读观察，不会消耗该记录，但重跑仍做一次兜底）。"""
    r = requests.post(f"{BASE}/api/login",
                      json={"username": "student01", "password": "123456"}, timeout=5)
    if r.status_code != 200:
        return None
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    acts = requests.get(f"{BASE}/api/activities", timeout=5).json()["activities"]
    act = next((a for a in acts if a["title"] == TARGET), None)
    if act is None:
        print(f"  （提示：活动「{TARGET}」不存在，请先确认演示数据）")
        return None
    mine = requests.get(f"{BASE}/api/my-activities", headers=h, timeout=5).json()["activities"]
    cur = next((a for a in mine if a["id"] == act["id"]), None)
    if cur and cur.get("reg_status") == "待审核":
        return act["id"]
    requests.delete(f"{BASE}/api/activities/{act['id']}/register", headers=h, timeout=5)
    requests.post(f"{BASE}/api/activities/{act['id']}/register", headers=h, timeout=5)
    print(f"  （已为「{TARGET}」重新生成一条待审核报名）")
    return act["id"]


def login(pg, username, password="123456"):
    pg.click('.user-area button:has-text("登录")')
    pg.wait_for_timeout(400)
    pg.fill('input[placeholder="登录账号"]', username)
    pg.fill('.modal input[type="password"]', password)
    pg.click('.modal button[type="submit"]')
    pg.wait_for_timeout(1500)


def logout(pg):
    btn = pg.locator('.user-area button:has-text("退出")')
    if btn.count():
        btn.first.click()
        pg.wait_for_timeout(800)


with sync_playwright() as p:
    aid = prepare_pending()

    b = p.chromium.launch(channel="msedge", headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
    pg = ctx.new_page()
    pg.on("dialog", lambda d: d.accept())

    # ---------------- 管理员 ----------------
    print("【1】管理员：活动广场的名单入口")
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_timeout(800)
    login(pg, "admin01")
    pg.wait_for_timeout(600)

    roster_btns = pg.locator('.act-card .act-foot button:has-text("报名名单")')
    chk("活动广场出现「报名名单」入口", roster_btns.count() >= 1, f"{roster_btns.count()} 个")
    chk("不再显示「平台管理员不参与报名」占位文字",
        pg.locator('text=（平台管理员不参与报名）').count() == 0)

    print()
    print("【2】管理员：名单弹层为只读")
    # 定位目标活动所在卡片
    card = pg.locator(".act-card", has=pg.locator(f'.act-title:text-is("{TARGET}")')).first
    card.locator('.act-foot button:has-text("报名名单")').click()
    pg.wait_for_timeout(1200)

    chk("名单弹层已打开", pg.locator(".modal-wide").count() >= 1)
    title = pg.locator(".modal-wide h3").first.inner_text().strip()
    chk("标题标注「只读」", "只读" in title, title)

    approve = pg.locator('.modal-wide button:has-text("通过")').count()
    reject = pg.locator('.modal-wide button:has-text("拒绝")').count()
    chk("无「通过」按钮", approve == 0, f"{approve} 个")
    chk("无「拒绝」按钮", reject == 0, f"{reject} 个")

    has_pending = pg.locator('.modal-wide .group-title:has-text("待审核")').count() >= 1
    if has_pending:
        hint = pg.locator('.modal-wide p.muted', has_text="管理员仅查看").count()
        chk("待审核分组下提示由教师处理审核", hint >= 1)
    else:
        print("  （该活动当前没有待审核报名，跳过审核提示检查）")

    # 名单内容仍可见：正式参加 / 候补中 至少有一组
    groups = [g.strip() for g in pg.locator(".modal-wide .group-title").all_inner_texts()]
    chk("名单内容对管理员可见", len(groups) >= 1, f"分组 {groups}")
    pg.screenshot(path=f"{OUT}/8_admin_roster_readonly.png", full_page=True)

    pg.locator(".modal-wide .modal-close").click()
    pg.wait_for_timeout(500)

    # ---------------- 教师（回归） ----------------
    print()
    print("【3】教师：审核按钮不受影响")
    logout(pg)
    login(pg, "teacher01")
    pg.wait_for_timeout(600)
    card2 = pg.locator(".act-card", has=pg.locator(f'.act-title:text-is("{TARGET}")')).first
    card2.locator('.act-foot button:has-text("报名名单")').click()
    pg.wait_for_timeout(1200)
    t_title = pg.locator(".modal-wide h3").first.inner_text().strip()
    chk("教师端标题不带「只读」", "只读" not in t_title, t_title)
    chk("教师端保留「通过」按钮", pg.locator('.modal-wide button:has-text("通过")').count() >= 1)
    pg.screenshot(path=f"{OUT}/9_teacher_roster.png", full_page=True)

    b.close()

print()
print("=" * 62)
print(f"结果：{PASS} 项通过 / {FAIL} 项失败")
print("=" * 62)
sys.exit(0 if FAIL == 0 else 1)
