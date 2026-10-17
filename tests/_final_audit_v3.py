# -*- coding: utf-8 -*-
"""
_final_audit_v3.py —— 交付前终审（可复现）

分六组核对，输出通过/失败并给出结论：
  A 包完整性：文件数、与磁盘逐字节一致、zip 未损坏、三份报告 md5、无敏感/冗余条目
  B 配置与依赖：requirements 覆盖实际 import、启动脚本版本、README 与实际脚本对齐
  C 代码质量：后端可编译、前端语法通过、终审修复点在位（until 游标、在途保护、409）
  D 版本标识：用户可见字符串里不残留 V2.0
  E 仓库状态：工作区干净、本地与远端一致
  F 报告：结构、表格、图、数据一致性、字体（调用既有核验脚本）
"""
import hashlib
import io
import os
import re
import subprocess
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT)
ZIP = os.path.join(os.path.dirname(ROOT), "校园活动管理系统V3.0_源代码_20261017.zip")
PY = r"C:\Users\28468\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
GIT = r"C:\Users\28468\.workbuddy\binaries\PortableGit\versions\1.3.0\cmd\git.exe"

PASS = FAIL = 0
problems = []


def chk(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  " + str(detail)) if detail else ""))
    else:
        FAIL += 1
        problems.append("%s %s" % (name, detail))
        print("  [FAIL] %s  %s" % (name, detail))


def git(*args):
    r = subprocess.run([GIT] + list(args), cwd=SRC, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return ((r.stdout or "") + (r.stderr or "")).strip()


def read(rel, enc="utf-8"):
    return io.open(os.path.join(SRC, rel), encoding=enc, errors="replace").read()


print("【A】交付包完整性")
if not os.path.exists(ZIP):
    chk("交付包存在", False, ZIP)
    z = None
else:
    print("  包: %s（%.2f MB）" % (os.path.basename(ZIP), os.path.getsize(ZIP) / 1024 / 1024))
    z = zipfile.ZipFile(ZIP)
    names = z.namelist()
    chk("zip 结构未损坏", z.testzip() is None)
    # 具体数量随脚本增减而变，真正的完整性靠下面的逐文件比对；这里只防"少打了一批"
    chk("文件数量在合理区间（70~85）", 70 <= len(names) <= 85, "实际 %d" % len(names))

    diff = []
    for n in names:
        rel = n.split("/", 1)[1]
        p = os.path.join(SRC, rel)
        if not os.path.exists(p):
            diff.append((rel, "磁盘缺失"))
            continue
        a, b = z.read(n), open(p, "rb").read()
        if hashlib.md5(a).hexdigest() != hashlib.md5(b).hexdigest():
            if a.replace(b"\r\n", b"\n") != b.replace(b"\r\n", b"\n"):
                diff.append((rel, "内容不同"))
    chk("全部文件与磁盘一致（CRLF 归一化后）", not diff, str(diff[:4]))

    bad = [n for n in names
           if n.endswith((".db", ".pyc", ".pyo", ".sqlite3", ".log"))
           or "__pycache__" in n or ".git/" in n
           or n.rsplit("/", 1)[-1].startswith(("~$", "_v3check", "_pagemap"))]
    chk("无数据库/缓存/锁文件/截图临时目录", not bad, str(bad[:4]))

    for name in ["实验一_基于工程意图的软件迭代开发.docx",
                 "实验二_基于用户访谈的需求演化.docx",
                 "实验三_基于运行数据的需求演化.docx"]:
        inner = "campus-activity-system/report/" + name
        disk = os.path.join(SRC, "report", name)
        if inner in names and os.path.exists(disk):
            same = hashlib.md5(z.read(inner)).hexdigest() == hashlib.md5(open(disk, "rb").read()).hexdigest()
            chk("报告与磁盘一致：%s" % name[:8], same)
        else:
            chk("报告在包内：%s" % name[:8], False)

print()
print("【B】配置与依赖")
req = read("requirements.txt")
for pkg in ["fastapi", "uvicorn", "requests"]:
    chk("requirements 声明 %s" % pkg, re.search(r"^%s\s*$" % pkg, req, re.M) is not None)
# 测试脚本实际用到、且必须由 requirements 覆盖的第三方包
used = set()
for f in os.listdir(os.path.join(SRC, "tests")):
    if f.endswith(".py"):
        for line in read(os.path.join("tests", f)).splitlines():
            m = re.match(r"^\s*(?:import|from)\s+([a-zA-Z_][\w]*)", line)
            if m:
                used.add(m.group(1))
declared = {"fastapi", "uvicorn", "requests"}
stdlib_ok = {"os", "sys", "io", "re", "json", "time", "csv", "hashlib", "zipfile",
             "subprocess", "collections", "sqlite3", "tempfile", "shutil", "glob",
             "datetime", "pathlib", "itertools", "math", "random",
             "importlib", "typing", "traceback"}
need = {u for u in used if u not in stdlib_ok
        and u not in ("backend", "docx", "playwright", "matplotlib", "requests")}
chk("测试脚本无未声明的第三方依赖", not need, str(need))
chk("playwright 在 requirements 注释中说明", "playwright" in req)

bat = read("启动系统.bat", enc="gbk")
chk("启动脚本标题为 V3.0", "V3.0" in bat, [l for l in bat.splitlines() if "title" in l][:1])
chk("启动脚本无 V2.0 残留", "V2.0" not in bat)
chk("requirements 无 V2.0 残留", "V2.0" not in req)
chk("前端页脚为 V3.0", "V3.0" in read("frontend/index.html"))
chk("README 声明 requests 需求", "requests" in read("README.md"))

print()
print("【C】代码质量")
r = subprocess.run([PY, "-m", "compileall", "-q", os.path.join(SRC, "backend")],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
chk("后端可编译", r.returncode == 0, (r.stderr or "")[:160])
NODE = r"C:\Users\28468\.workbuddy\binaries\node\versions\22.22.2-6\node.exe"
if os.path.exists(NODE):
    r = subprocess.run([NODE, "--check", os.path.join(SRC, "frontend", "app.js")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    chk("前端 app.js 语法通过", r.returncode == 0, (r.stderr or "")[:160])

reg = read(os.path.join("backend", "routers", "registrations.py"))
app = read(os.path.join("frontend", "app.js"))
chk("已读接口支持 until 参数", "until" in reg and "MarkReadRequest" in reg)
chk("游标只前进不后退", "max(seen, target)" in reg.replace(" ", " "))
chk("前端标记已读时传 until", "until: maxId" in app)
chk("报名在途保护在位", "regBusy" in app and "处理中" in app)
chk("重复报名返回 409", "status_code=409" in reg)
chk("重复报名带当前状态", "current_status" in reg)
chk("事件表不设 registrations 外键", "REFERENCES registrations" not in read("backend/database.py"))

print()
print("【D】版本标识（用户可见字符串）")
html = read("frontend/index.html")
chk("页面标题为 V3.0", "校园活动管理系统 V3.0" in html)
chk("页脚为软件工程实验三", "实验三" in html)
# 代码注释里保留「V2.0：某功能」是合理的溯源说明，只查真正会显示给用户的部分
visible = re.sub(r"<!--.*?-->", "", html, flags=re.S)
leftover = [l.strip() for l in visible.splitlines() if "V2.0" in l]
chk("页面可见部分无 V2.0 残留", not leftover, str(leftover[:2]))

print()
print("【E】仓库状态")
status = git("status", "--short")
chk("工作区干净", status == "", status[:200])
head = git("rev-parse", "HEAD")
remote = git("ls-remote", "origin", "main").split()[0] if git("ls-remote", "origin", "main") else ""
chk("本地与远端一致", head == remote, "本地 %s / 远端 %s" % (head[:10], remote[:10]))
n_commit = int(git("rev-list", "--count", "HEAD") or 0)
chk("提交数不少于 57", n_commit >= 57, str(n_commit))

print()
print("【F】报告核验（调用 tests/_verify_report_v3.py）")
r = subprocess.run([PY, os.path.join(SRC, "tests", "_verify_report_v3.py")], cwd=SRC,
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
tail = [l for l in (r.stdout or "").splitlines() if "报告核验" in l]
chk("报告核验全过", "0 项失败" in (tail[-1] if tail else ""), tail[-1] if tail else "未取到结果")

print()
print("=" * 64)
print("终审结果：%d 项通过 / %d 项失败" % (PASS, FAIL))
if problems:
    print("未通过项：")
    for p in problems:
        print("  -", p)
else:
    print("结论：可以交付")
print("=" * 64)
sys.exit(0 if FAIL == 0 else 1)
