# -*- coding: utf-8 -*-
"""
_verify_report_v3.py —— 从磁盘读回 V3.0 报告，核对是否填完、是否与数据一致

核对点：
1. 五章标题齐全、顺序正确
2. 三张表行数正确、单元格无空缺、无模板占位残留
3. 基本信息内容正确
4. 三张图均在位且不超过可用宽度
5. 正文引用的关键数字与数据包实算值一致
6. 无半角标点、无模板提示语残留（【填写…】）
7. 篇幅与段落数合理
"""
import io
import os
import sys

import csv
from collections import Counter

from docx import Document
from docx.shared import Emu

sys.stdout.reconfigure(encoding="utf-8")

P = r"report\实验三_基于运行数据的需求演化.docx"
DATA = os.path.join("..", "_exp3", "data", "项目数据", "data")
PASS = FAIL = 0


def chk(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  " + detail) if detail else ""))
    else:
        FAIL += 1
        print("  [FAIL] %s  %s" % (name, detail))


def rd(name):
    with io.open(os.path.join(DATA, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


d = Document(P)
texts = [p.text.strip() for p in d.paragraphs]
full = "\n".join(texts)
for tb in d.tables:
    for row in tb.rows:
        for c in row.cells:
            full += "\n" + c.text

print("【1】章节结构")
heads = [p.text.strip() for p in d.paragraphs if p.style.name == "Heading 1"]
want = ["一、基本信息", "二、数据分析与问题发现", "三、需求调整及其依据",
        "四、设计与 V3.0 迭代实现", "五、验证结果与效果分析"]
chk("五个一级标题齐全且顺序正确", heads == want, " / ".join(heads))

print()
print("【2】表格")
chk("表格数为 3", len(d.tables) == 3, "%d 张" % len(d.tables))
t0, t1, t2 = d.tables
chk("基本信息表 6 行 2 列（含代码仓库行）", len(t0.rows) == 6 and len(t0.columns) == 2,
    "%d×%d" % (len(t0.rows), len(t0.columns)))
chk("需求调整表 3 行（表头 + 2 条需求）", len(t1.rows) == 3, "%d 行" % len(t1.rows))
chk("验证结果表 7 行（表头 + 6 条验证）", len(t2.rows) == 7, "%d 行" % len(t2.rows))

empty = []
for ti, tb in enumerate(d.tables):
    for ri, row in enumerate(tb.rows):
        for ci, c in enumerate(row.cells):
            if not c.text.strip():
                empty.append((ti, ri, ci))
chk("三张表无空单元格", not empty, str(empty[:5]))

print()
print("【3】基本信息")
chk("班级勾选 6 班", "☑ 6 班" in t0.rows[1].cells[1].text, t0.rows[1].cells[1].text.strip())
chk("组名正确", t0.rows[2].cells[1].text.strip() == "之乎者也", t0.rows[2].cells[1].text.strip())
chk("组员姓名正确", t0.rows[3].cells[1].text.strip() == "肖子恒", t0.rows[3].cells[1].text.strip())
chk("组内分工已填", len(t0.rows[4].cells[1].text.strip()) > 8, t0.rows[4].cells[1].text.strip()[:30])
REPO = "https://github.com/Num1AD/campus-activity-system"
chk("基本信息含可访问的代码仓库地址",
    t0.rows[5].cells[0].text.strip() == "代码仓库" and t0.rows[5].cells[1].text.strip() == REPO,
    t0.rows[5].cells[1].text.strip())
chk("第四章版本记录也给出仓库地址", REPO in full)

print()
print("【4】图片")
sec = d.sections[0]
usable = Emu(sec.page_width - sec.left_margin - sec.right_margin).cm
chk("四张图均在位", len(d.inline_shapes) == 4, "%d 张" % len(d.inline_shapes))
overs = [i + 1 for i, sh in enumerate(d.inline_shapes) if sh.width.cm > usable + 0.05]
chk("图片均不超过可用宽度 %.2f cm" % usable, not overs, "超宽: %s" % overs)
chk("图题齐全且顺序正确",
    all(k in full for k in ["图 2-1", "图 2-2", "图 4-1", "图 4-2"]))
chk("图 4-1 为状态流转图", "图 4-1　报名状态流转与事件记录" in full)
chk("图 4-2 为界面截图", "图 4-2　「我的活动」" in full)

print()
print("【5】正文数字与数据包实算值一致")
reg = rd("registration_log.csv")
wait = rd("waitlist_log.csv")
apply_rows = [r for r in reg if r["action"] == "apply"]
cnt = Counter(r["result"] for r in apply_rows)
wl = {r["application_id"] for r in wait}
wl_ok = {r["application_id"] for r in wait if r["new_status"] == "accepted"}
pairs = [
    ("报名申请 2 748 条", "2 748", len(apply_rows)),
    ("直接成功 1 689 条", "1 689", cnt["accepted"]),
    ("进入候补 876 条", "876", cnt["waitlisted"]),
    ("重复提交 126 条", "126", cnt["duplicate"]),
    ("名额冲突 41 条", "41", cnt["capacity_conflict"]),
    ("服务端错误 16 条", "16", cnt["server_error"]),
    ("候补申请 876 个", "876", len(wl)),
    ("递补成功 130 个", "130", len(wl_ok)),
]
bad = [(label, doc_v, real) for label, doc_v, real in pairs if doc_v not in full]
chk("八项关键数字都能在正文找到", not bad, str(bad))
chk("候补转化率 14.8% 在正文", "14.8%" in full)
chk("等待中位数 1 085 分钟在正文", "1 085" in full)
chk("满员分支 1 308 毫秒在正文", "1 308" in full)

print()
print("【6】残留与标点")
chk("无模板占位【填写…】残留", "【填写" not in full,
    [t[:40] for t in texts if "【填写" in t][:3])
chk("标题已去掉「模板」二字", "实验报告模板" not in full)
chk("无占位词 TODO/待补", not any(k in full for k in ["TODO", "待补", "xxx", "XXX"]))

# 网址本身必然含半角冒号与斜杠，检查标点前先剔除，否则会把正常的仓库地址判成问题
import re as _re
no_url = _re.sub(r"https?://[^\s）)]+", "", full)
half = [ch for ch in ['"', "'", ",", ";", ":", "?", "!"] if ch in no_url]
chk("正文无半角标点（已剔除网址）", not half, "出现: %s" % half)

print()
print("【7】字体与字号一致性")
from docx.oxml.ns import qn
from collections import Counter as _C

fonts = _C()
para_sizes = _C()
tbl_sizes = _C()
marks = _C()
for pp in d.paragraphs:
    for r in pp.runs:
        if not pp.text.strip():
            continue
        fonts[str(r.font.name)] += 1
        key = "标题继承" if pp.style.name in ("Title", "Heading 1") else str(
            r.font.size.pt if r.font.size else "继承")
        para_sizes[key] += 1
    pPr = pp._p.pPr
    if pPr is not None:
        rpr = pPr.find(qn("w:rPr"))
        if rpr is not None and rpr.find(qn("w:sz")) is not None:
            marks["显式"] += 1
for tb in d.tables:
    for row in tb.rows:
        for c in row.cells:
            for pp in c.paragraphs:
                for r in pp.runs:
                    fonts[str(r.font.name)] += 1
                    tbl_sizes[str(r.font.size.pt if r.font.size else "继承")] += 1

chk("全文字体只有微软雅黑", set(fonts) == {"微软雅黑"}, str(dict(fonts)))
chk("正文字号只有 10.5 / 副标题 10 / 图题 9 / 标题继承",
    set(para_sizes) <= {"10.5", "10.0", "9.0", "标题继承"}, str(dict(para_sizes)))
chk("表格统一 9pt", set(tbl_sizes) == {"9.0"}, str(dict(tbl_sizes)))
chk("段落标记无显式字号（空段落行高一致）", not marks, str(dict(marks)))
chk("标题样式已改为显式微软雅黑（不依赖主题字体）",
    "majorEastAsia" not in d.styles["Heading 1"].element.xml,
    "仍引用主题字体" if "majorEastAsia" in d.styles["Heading 1"].element.xml else "")

print()
print("【8】篇幅")
body_chars = sum(len(p.text.strip()) for p in d.paragraphs if p.style.name == "Normal")
table_chars = sum(len(c.text.strip()) for tb in d.tables for row in tb.rows for c in row.cells)
chk("正文（不含表格）不少于 2 000 字", body_chars >= 2000, "%d 字" % body_chars)
print("      正文 %d 字 / 表格 %d 字 / 段落 %d 个" % (body_chars, table_chars, len(d.paragraphs)))
print("      文件 %.1f KB" % (os.path.getsize(P) / 1024))

print()
print("=" * 62)
print("报告核验：%d 项通过 / %d 项失败" % (PASS, FAIL))
print("=" * 62)
sys.exit(0 if FAIL == 0 else 1)
