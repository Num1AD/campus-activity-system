"""
_verify_report_admin_roster.py —— 从磁盘读回报告，逐项核对本轮改动

要点：必须从磁盘重新读取（edsdk 保存后再读），否则读到的是内存里的旧内容。
同时检查结构完整性，确认新增段落/行没有破坏文档。
"""

import sys
import zipfile

from docx import Document

sys.stdout.reconfigure(encoding="utf-8")

P = r"report\实验二_基于用户访谈的需求演化.docx"
PASS = FAIL = 0


def chk(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


d = Document(P)


def cell(ti, ri, ci):
    return d.tables[ti].rows[ri].cells[ci].text.strip()


print("【1】第五章 角色与权限边界（管理员行）")
c2, c3, c4 = cell(6, 3, 1), cell(6, 3, 2), cell(6, 3, 3)
chk("允许的操作含名单只读查看", "查看平台全部活动的报名与候补名单" in c2)
chk("明确不能执行的操作精确到处理动作",
    "审核报名、调整候补顺序或判定名额归属" in c3 and "名单只可查看，不可处理" in c3)
chk("依据列标明属第八章设计约定", "第八章的设计约定" in c4)

print()
print("【2】第六章 US-08 验收标准")
acc = cell(7, 8, 2)
chk("权限段已更新", "报名与候补名单可以只读查看用于监督核实" in acc)
chk("仍为正常/异常/权限 三段结构",
    acc.count("\n") == 2 and acc.startswith("正常：") and "权限：" in acc,
    f"段数={acc.count(chr(10)) + 1}")

print()
print("【3】第七章 角色体系与账号管理行")
v2, how = cell(8, 6, 2), cell(8, 6, 4)
chk("变化列含名单查看", "及其报名与候补名单用于监督" in v2)
chk("变化列区分查看权与处理权", "对报名业务只有查看权限，没有处理权限" in v2)
chk("处理方式列含只读标记", "名单接口对管理员开放只读查看" in how)

print()
print("【4】第九章 开发与Git过程（前端适配行）")
commits, note = cell(9, 6, 2), cell(9, 6, 3)
chk("提交列补入本轮三次提交", all(c in commits for c in ("efbd2f4", "cc86ec9", "db0635a")), commits)
chk("说明列用例数已更新为 38/47",
    "38 条全部通过" in note and "审核与管理员 47 项" in note)
chk("说明列含管理员名单只读 10 项", "管理员名单只读 10 项" in note)

print()
print("【5】第十章 测试与验证（表格）")
t11 = d.tables[10]
chk("表格行数 9 → 10", len(t11.rows) == 10, f"{len(t11.rows)} 行")
last = [c.text.strip() for c in t11.rows[9].cells]
chk("新增行内容正确",
    last[0] == "TEST-37" and "只读查看" in last[3] and last[5] == "通过",
    " | ".join(last)[:80])
chk("原有 8 条用例保留",
    [r.cells[0].text.strip() for r in t11.rows[1:9]] ==
    ["TEST-25", "TEST-26", "TEST-27", "TEST-28", "TEST-30", "TEST-32", "TEST-33", "TEST-36"])

print()
print("【6】第八章 新增第 7 条 / 第 6 条措辞")
texts = [p.text.strip() for p in d.paragraphs]
full = "\n".join(texts)
chk("第八章第 6 条已改为「不参与具体报名业务的处理」",
    "6. 权限边界：管理员的写操作限于账号状态与活动状态处理，不参与具体报名业务的处理。" in full)
chk("第八章第 7 条已插入",
    any(t.startswith("7. 名单查看范围：") for t in texts))
chk("第 7 条标明设计约定性质",
    any("不作为访谈得到的独立需求" in t for t in texts))
# 第 6 条与第 7 条应相邻
idx6 = next(i for i, t in enumerate(texts) if t.startswith("6. 权限边界："))
idx7 = next(i for i, t in enumerate(texts) if t.startswith("7. 名单查看范围："))
chk("第 6、7 条相邻且在第 5 条之后",
    idx7 > idx6 and texts[idx6 - 1].startswith("5. 账号停用"), f"段 {idx6} → {idx7}")

print()
print("【7】第十章 正文过程记录")
chk("新增第（4）条测试脚本状态残留",
    any(t.startswith("（4）测试脚本的状态残留问题：") for t in texts))
i4 = next(i for i, t in enumerate(texts) if t.startswith("（4）测试脚本"))
chk("第（4）条排在（3）之后",
    texts[i4 - 1].startswith("（3）前端实测中的失败项"), texts[i4 - 1][:30])

print()
print("【8】结构完整性")
chk("段落数 ≥ 130", len(d.paragraphs) >= 130, f"{len(d.paragraphs)} 段")
chk("表格数仍为 13", len(d.tables) == 13, f"{len(d.tables)} 张")
z = zipfile.ZipFile(P)
chk("ZIP 结构完好", z.testzip() is None)
media = [n for n in z.namelist() if n.startswith("word/media/") and not n.endswith("/")]
chk("图 8-1 的图片文件在位",
    any(n.endswith("image1.png") for n in media) and len(d.inline_shapes) == 1,
    f"{media} / 内联图片 {len(d.inline_shapes)} 张")

print()
print("=" * 62)
print(f"核验结果：{PASS} 项通过 / {FAIL} 项失败")
print("=" * 62)
sys.exit(0 if FAIL == 0 else 1)
