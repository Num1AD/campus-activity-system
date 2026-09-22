"""
_verify_frontend_v2.py —— V2.0 前端功能实测（playwright + 系统 Edge 无头模式）

验证点：
1. 未登录活动广场：显示「需审核」标记与参加资格
2. 学生「我的活动」：显示本人报名状态（正式参加 / 候补中 / 待审核）
3. 满员活动按钮文案：显示「报名（进入候补）」
4. 教师报名名单：待审核 / 正式参加 / 候补中 三组分组显示
5. 教师审核：通过一条待审核报名
6. 管理员账号管理：查看账号列表并停用/恢复

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

PASS = FAIL = 0


def ensure_pending_registration():
    """
    确保「【V2演示】安全培训」存在一条待审核报名。

    本脚本会执行"审核通过"操作，重复运行后该记录就不再是待审核状态，
    因此每次运行前先恢复：若已不是待审核，则撤回后重新报名。
    """
    r = requests.post(f"{BASE}/api/login",
                      json={"username": "student01", "password": "123456"}, timeout=5)
    if r.status_code != 200:
        return None
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    acts = requests.get(f"{BASE}/api/activities", timeout=5).json()["activities"]
    act = next((a for a in acts if a["title"] == "【V2演示】安全培训"), None)
    if act is None:
        print("  （提示：演示活动「【V2演示】安全培训」不存在，请先运行 _seed_v2_demo.py）")
        return None
    mine = requests.get(f"{BASE}/api/my-activities", headers=h, timeout=5).json()["activities"]
    cur = next((a for a in mine if a["id"] == act["id"]), None)
    if cur and cur.get("reg_status") == "待审核":
        return act["id"]
    requests.delete(f"{BASE}/api/activities/{act['id']}/register", headers=h, timeout=5)
    requests.post(f"{BASE}/api/activities/{act['id']}/register", headers=h, timeout=5)
    print("  （已为「【V2演示】安全培训」重新生成一条待审核报名）")
    return act["id"]


def chk(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def login(pg, username, password="123456"):
    """在页面上完成登录。"""
    pg.click('.user-area button:has-text("登录")')
    pg.wait_for_timeout(400)
    pg.fill('input[placeholder="登录账号"]', username)
    pg.fill('.modal input[type="password"]', password)
    pg.click('.modal button[type="submit"]')
    pg.wait_for_timeout(1500)


with sync_playwright() as p:
    # 先恢复测试前置状态（脚本可重复运行）
    ensure_pending_registration()

    b = p.chromium.launch(channel="msedge", headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
    pg = ctx.new_page()
    pg.on("dialog", lambda d: d.accept())

    # ---------------- 1. 未登录：活动广场 ----------------
    print("【1】未登录活动广场")
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_timeout(900)
    n_card = pg.locator(".act-card").count()
    n_review = pg.locator(".tag-review").count()
    n_elig = pg.locator(".act-eligibility").count()
    chk("活动卡片正常渲染", n_card >= 3, f"{n_card} 张")
    chk("显示「需审核」标记", n_review >= 1, f"{n_review} 个")
    chk("显示参加资格说明", n_elig >= 1, f"{n_elig} 处")
    pg.screenshot(path=f"{OUT}/1_plaza_guest.png", full_page=True)

    # ---------------- 2. 学生登录 → 我的活动 ----------------
    # 用 student02：他在「人工智能前沿讲座」「迎新志愿服务」都是候补中，
    # 便于同时验证「正式参加 / 候补中」两种状态的展示
    print()
    print("【2】学生端：报名状态展示与按钮文案")
    login(pg, "student02")
    pg.click('.nav-btn:has-text("我的活动")')
    pg.wait_for_timeout(1200)
    tags = [t.strip() for t in pg.locator(".act-card .mini-tag").all_inner_texts()]
    cards = pg.locator(".act-card").all_inner_texts()
    chk("我的活动显示报名状态标签", len(tags) >= 2, f"标签 {tags}")
    chk("含「候补中」状态", "候补中" in tags, f"{tags}")
    chk("含「正式参加」状态", "正式参加" in tags, f"{tags}")
    foots = [t.strip() for t in pg.locator(".act-foot").all_inner_texts()]
    chk("候补卡片显示「退出候补」按钮", any("退出候补" in t for t in foots), f"{foots}")
    pg.screenshot(path=f"{OUT}/2_student_mine.png", full_page=True)

    # 学生：满员活动按钮文案
    pg.click('.nav-btn:has-text("活动广场")')
    pg.wait_for_timeout(900)
    btns = [t.strip() for t in pg.locator(".act-card .act-foot button").all_inner_texts()]
    chk("满员活动按钮提示进入候补", any("进入候补" in t for t in btns), f"按钮文案 {btns}")
    chk("已候补的活动按钮为「退出候补」", any("退出候补" in t for t in btns), f"{btns}")
    pg.screenshot(path=f"{OUT}/2b_plaza_student.png", full_page=True)

    # 退出学生账号
    pg.click('.user-area button:has-text("退出")')
    pg.wait_for_timeout(900)

    # ---------------- 3. 教师端：名单分组与审核 ----------------
    print()
    print("【3】教师端：名单分组与审核")
    login(pg, "teacher01")
    pg.click('.nav-btn:has-text("我的活动")')
    pg.wait_for_timeout(1200)
    titles = pg.locator(".act-card .act-title").all_inner_texts()
    chk("教师活动列表渲染", len(titles) >= 3, f"{titles}")
    meta = pg.locator(".act-card .act-meta").all_inner_texts()
    chk("教师卡片显示候补人数", any("候补" in m for m in meta), f"{meta[:3]}")

    # 打开「【V2演示】安全培训」的名单（有一条待审核）
    target = pg.locator(".act-card", has=pg.locator(".act-title", has_text="【V2演示】安全培训"))
    target.locator('button:has-text("报名名单")').click()
    pg.wait_for_timeout(1000)
    groups = pg.locator(".modal .group-title").all_inner_texts()
    chk("名单弹层分组标题", any("待审核" in g for g in groups), f"{groups}")
    pg.screenshot(path=f"{OUT}/3_teacher_list_modal.png", full_page=True)

    n_pending_before = pg.locator(".modal .op-cell").count()
    chk("待审核行带审核操作按钮", n_pending_before >= 1, f"{n_pending_before} 行")

    # 执行审核通过
    pg.locator('.modal .op-cell button:has-text("通过")').first.click()
    pg.wait_for_timeout(1500)
    groups2 = pg.locator(".modal .group-title").all_inner_texts()
    body2 = pg.locator(".modal").inner_text()
    chk("审核通过后名单刷新", "正式参加" in body2, f"分组 {groups2}")
    pg.screenshot(path=f"{OUT}/4_after_review.png", full_page=True)
    pg.locator(".modal .modal-close").click()
    pg.wait_for_timeout(500)

    pg.click('.user-area button:has-text("退出")')
    pg.wait_for_timeout(900)

    # ---------------- 4. 管理员端 ----------------
    print()
    print("【4】管理员端：账号管理")
    login(pg, "admin01")
    navs = pg.locator(".nav-btn").all_inner_texts()
    chk("管理员导航含「账号管理」", any("账号管理" in n for n in navs), f"{navs}")
    chk("管理员不显示「我的活动」", not any("我的活动" in n for n in navs), f"{navs}")
    pg.click('.nav-btn:has-text("账号管理")')
    pg.wait_for_timeout(1200)
    rows = pg.locator(".admin-table tbody tr").count()
    chk("账号表格渲染", rows >= 4, f"{rows} 行")
    roles = pg.locator(".admin-table .role-badge").all_inner_texts()
    chk("含三种角色", {"学生", "教师", "管理员"} <= set(r.strip() for r in roles), f"{sorted(set(roles))}")
    self_btn_disabled = pg.locator(".admin-table tbody tr", has_text="admin01").locator("button").first.is_disabled()
    chk("当前登录管理员不能停用自己（按钮禁用）", self_btn_disabled)
    pg.screenshot(path=f"{OUT}/5_admin_users.png", full_page=True)

    # 停用「小红」账号
    row = pg.locator(".admin-table tbody tr", has_text="小红")
    row.locator('button:has-text("停用")').click()
    pg.wait_for_timeout(1400)
    row2 = pg.locator(".admin-table tbody tr", has_text="小红")
    chk("停用后状态显示为「已停用」", "已停用" in row2.inner_text(), row2.inner_text()[:60])
    pg.screenshot(path=f"{OUT}/6_admin_disabled.png", full_page=True)

    # 恢复
    row2.locator('button:has-text("恢复")').click()
    pg.wait_for_timeout(1400)
    row3 = pg.locator(".admin-table tbody tr", has_text="小红")
    chk("恢复后状态回到「可用」", "可用" in row3.inner_text(), row3.inner_text()[:60])

    b.close()

print()
print("=" * 70)
print(f"前端实测：{PASS} 项通过 / {FAIL} 项失败")
print(f"截图输出目录：{OUT}")
print("=" * 70)
sys.exit(0 if FAIL == 0 else 1)
