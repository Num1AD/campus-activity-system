"""
_verify_docs_sync.py —— 校验 docs/ 里的设计说明与代码是否一致

背景：docs/01~04 是 V1.0 阶段的文档，V2.0 的调整此前只写在报告里，导致交付包里
文档描述的是 V1.0、代码却是 V2.0。补上 docs/05 之后又出现同样的问题：V3.0 的改动
一开始也只写在设计里。两个文档都必须与代码逐项对得上，否则又是新一轮漂移。

校验方式：
1. 从 docs/05 与 docs/06 提取反引号里的表字段名，逐个到 backend/database.py 找
2. 从两份文档提取 /api/... 形式的接口路径，逐个到 backend/routers/ 与 main.py 找
3. 确认 docs/04、01 已加指引，05 已指向 06，避免读者误把旧版本当现状
"""

import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
PASS = FAIL = 0


def chk(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


docs05 = io.open(r"docs\05-V2.0设计调整.md", encoding="utf-8").read()
docs06 = io.open(r"docs\06-V3.0设计调整.md", encoding="utf-8").read()
docs_all = docs05 + "\n" + docs06
db = io.open(r"backend\database.py", encoding="utf-8").read()
main_src = io.open(r"backend\main.py", encoding="utf-8").read()

# 各路由模块的挂载前缀：定义在各文件自己的 APIRouter(prefix=...) 里
# （main.py 的 include_router 未传 prefix，容易看漏，这里按实际写法提取）
prefix_map = {}
for f in sorted(os.listdir(r"backend\routers")):
    if not f.endswith(".py") or f == "__init__.py":
        continue
    src = io.open(os.path.join(r"backend\routers", f), encoding="utf-8").read()
    m = re.search(r"APIRouter\(\s*prefix\s*=\s*[\"']([^\"']+)[\"']", src)
    prefix_map[f[:-3]] = m.group(1) if m else ""

# 完整路由表：模块前缀 + 各文件内的路径
route_table = []
for f in sorted(os.listdir(r"backend\routers")):
    if not f.endswith(".py") or f == "__init__.py":
        continue
    mod = f[:-3]
    src = io.open(os.path.join(r"backend\routers", f), encoding="utf-8").read()
    prefix = prefix_map.get(mod, "")
    for m in re.finditer(r"@router\.(get|post|put|delete)\(\s*[\"']([^\"']+)[\"']", src):
        full = (prefix + "/" + m.group(2).strip("/")).replace("//", "/")
        route_table.append((m.group(1).upper(), full))

routes_src = main_src + "".join(
    io.open(os.path.join(r"backend\routers", f), encoding="utf-8").read()
    for f in sorted(os.listdir(r"backend\routers")) if f.endswith(".py"))

print("【1】文档提到的数据字段都在建表语句里")
# 反引号标识符里，除了数据库字段还包含接口返回字段与普通名词，逐个分类
INTERFACE_ONLY = {
    "readonly",         # V2.0：名单接口的只读标记
    "queue_position",   # V3.0：候补排队位置（按 queued_at 现算，不落库）
    "waitlist_total",   # V3.0：候补总人数（现算）
    "current_status",   # V3.0：重复报名的 409 响应字段
    "unread_count",     # V3.0：未读条数（现算）
    "last_seen_at",     # V3.0：已读时间（由游标反查）
    "until",            # V3.0：标记已读接口的可选请求参数，不是表字段
}
KEEP_AS_IS = {"confirmed", "pending", "waitlisted", "student", "teacher", "admin"}
# 事件原因代码：不是表字段，而是写入 registration_events.reason 的枚举值，
# 单独到 helpers.py 里核对才有意义（见下方检查）
REASON_CODES = {"review_approved", "review_waitlisted", "review_rejected"}
# 指向教师模拟数据的取值，本组表结构里本就没有（文档已明写"本组不存在"）
EXTERNAL_DATA = {"duplicate", "category", "colloquial"}
fields = set(re.findall(r"`([a-z_][a-z0-9_]{2,})`", docs_all))
db_fields = sorted(fields - INTERFACE_ONLY - KEEP_AS_IS - REASON_CODES - EXTERNAL_DATA)
missing = [f for f in db_fields if f not in db]
chk(f"两份文档中的 {len(db_fields)} 个字段名标注均能在 database.py 找到",
    not missing, f"未找到: {missing}" if missing else "")

helpers_src = io.open(r"backend\helpers.py", encoding="utf-8").read()
chk("事件原因代码在 helpers.py 中定义",
    all(c in helpers_src for c in REASON_CODES),
    " / ".join(sorted(c for c in REASON_CODES if c not in helpers_src)) or "")

for f in ["is_active", "require_review", "eligibility", "queued_at"]:
    chk(f"V2.0 关键字段 {f} 在建表语句中", f in db)
for f in ["registration_events", "needs_notice", "events_seen_id", "from_status", "to_status"]:
    chk(f"V3.0 关键字段 {f} 在建表语句中", f in db)

for f in INTERFACE_ONLY:
    chk(f"接口字段 {f} 在后端代码中（非数据库字段）", f in routes_src)

print()
print("【2】文档提到的接口路径都在路由里")
paths = sorted(set(re.findall(r"`(/api/[^`]+)`", docs_all)))
missing_paths = []
for p in paths:
    core = p.split("?")[0]
    seg = core.replace("/api", "", 1).strip("/")
    base = re.sub(r"\{[^}]+\}", "", seg).strip("/")
    hit = False
    for _method, route in route_table:
        route_base = re.sub(r"\{[^}]+\}", "", route.replace("/api", "", 1)).strip("/")
        if route_base == base or (base and route_base.startswith(base)):
            hit = True
            break
    if not hit:
        missing_paths.append(p)
chk(f"文档中的 {len(paths)} 个接口路径均能在路由中找到对应（含 main.py 的挂载前缀）",
    not missing_paths, f"未匹配: {missing_paths}" if missing_paths else "")
print(f"      后端实际路由 {len(route_table)} 条：")
for method, route in route_table:
    print(f"        {method:<6} {route}")

print()
print("【3】待审核 / 正式参加 / 候补中 三个状态名在代码中一致")
for en, cn in [("pending", "待审核"), ("confirmed", "正式参加"), ("waitlisted", "候补中")]:
    in_db = f"'{en}'" in db or f'"{en}"' in db
    in_doc = en in docs05
    chk(f"状态 {cn}（{en}）代码与文档都有", in_db and in_doc,
        f"代码={in_db} 文档={in_doc}")

print()
print("【4】旧版本文档已加指引，不会被误读为当前状态")
d04 = io.open(r"docs\04-软件设计.md", encoding="utf-8").read()
d01 = io.open(r"docs\01-需求分析.md", encoding="utf-8").read()
chk("04-软件设计.md 指向 05", "05-V2.0设计调整.md" in d04)
chk("01-需求分析.md 说明 V2.0 需求在报告中", "V2.0 由用户访谈确认的需求" in d01)
chk("05 开头说明自己是 V2.0 调整", "V1.0（V1.0）阶段" in docs05 or "实验一（V1.0）阶段" in docs05)
chk("05 已指向 06（V3.0 调整）", "06-V3.0设计调整.md" in docs05)
chk("06 说明 04+05+06 才是完整设计", "04 + 05 + 06" in docs06)

print()
print("【5】docs 目录结构")
docs = sorted(f for f in os.listdir("docs") if f.endswith(".md"))
chk("docs 共 6 份文档（01~06）", len(docs) == 6, " / ".join(docs))

print()
print("【6】V3.0 新增接口在文档与代码中都存在")
for p in ["/api/my-registration-events", "/api/my-registration-events/read"]:
    in_code = any(p == route.replace("/api", "/api", 1) or route.endswith(p.replace("/api", ""))
                  for _m, route in route_table)
    in_code = any(route.replace("/api", "") == p.replace("/api", "") for _m, route in route_table)
    chk(f"接口 {p} 在代码中", in_code)
    chk(f"接口 {p} 在文档中", p in docs06)

print()
print("=" * 62)
print(f"核验结果：{PASS} 项通过 / {FAIL} 项失败")
print("=" * 62)
sys.exit(0 if FAIL == 0 else 1)
