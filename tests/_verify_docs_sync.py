"""
_verify_docs_sync.py —— 校验 docs/ 里的设计说明与代码是否一致

背景：docs/01~04 是 V1.0 阶段的文档，V2.0 的调整此前只写在报告里，导致交付包里
文档描述的是 V1.0、代码却是 V2.0。刚补的 docs/05-V2.0设计调整.md 必须与代码
逐项对得上，否则又是新一轮漂移。

校验方式：
1. 从 docs/05 提取反引号里的表字段名，逐个到 backend/database.py 的建表语句里找
2. 从 docs/05 提取 /api/... 形式的接口路径，逐个到 backend/routers/ 与 main.py 里找
3. 确认 docs/04 与 docs/01 已加「V2.0 变更见 05」的指引，避免读者误把 V1.0 当现状
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
INTERFACE_ONLY = {"readonly"}          # 接口返回字段，不在建表语句里
KEEP_AS_IS = {"confirmed", "pending", "waitlisted", "student", "teacher", "admin"}
fields = set(re.findall(r"`([a-z_][a-z0-9_]{2,})`", docs05))
db_fields = sorted(fields - INTERFACE_ONLY - KEEP_AS_IS)
missing = [f for f in db_fields if f not in db]
chk(f"文档中的 {len(db_fields)} 个字段名标注均能在 database.py 找到",
    not missing, f"未找到: {missing}" if missing else "")

for f in ["is_active", "require_review", "eligibility", "queued_at"]:
    chk(f"关键字段 {f} 在建表语句中", f in db)

for f in INTERFACE_ONLY:
    chk(f"接口字段 {f} 在后端代码中（非数据库字段）", f in routes_src)

print()
print("【2】文档提到的接口路径都在路由里")
paths = sorted(set(re.findall(r"`(/api/[^`]+)`", docs05)))
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
print("【4】V1.0 文档已加指引，不会被误读为当前状态")
d04 = io.open(r"docs\04-软件设计.md", encoding="utf-8").read()
d01 = io.open(r"docs\01-需求分析.md", encoding="utf-8").read()
chk("04-软件设计.md 指向 05", "05-V2.0设计调整.md" in d04)
chk("01-需求分析.md 说明 V2.0 需求在报告中", "V2.0 由用户访谈确认的需求" in d01)
chk("05 开头说明自己是 V2.0 调整", "V1.0（V1.0）阶段" in docs05 or "实验一（V1.0）阶段" in docs05)

print()
print("【5】docs 目录结构")
docs = sorted(f for f in os.listdir("docs") if f.endswith(".md"))
chk("docs 共 5 份文档", len(docs) == 5, " / ".join(docs))

print()
print("=" * 62)
print(f"核验结果：{PASS} 项通过 / {FAIL} 项失败")
print("=" * 62)
sys.exit(0 if FAIL == 0 else 1)
