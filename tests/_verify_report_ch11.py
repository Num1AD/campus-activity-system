"""
_verify_report_ch11.py —— 从磁盘读回报告，核对第十一章（AI 使用记录）填写结果

核对点：
1. AI 记录表 4 行 × 4 列全部填写，无空单元格
2. 「本组如何检查/修改」列不含问法命中率一类的表述（用户明确要求删除，避免读起来像用 AI 生成访谈）
3. 工具列写明模型名
4. 模板原话说明句未被改动
5. 文档结构未受破坏（13 张表、图 8-1 在位），且第十二章仍是空的（本轮不动它）
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
t = d.tables[11]
rows = [[c.text.strip() for c in r.cells] for r in t.rows]

print("【1】AI 记录表填写完整性")
chk("表头未变", rows[0] == ["使用环节", "使用的AI工具", "AI主要帮助内容", "本组如何检查/修改"],
    " | ".join(rows[0]))
empty = [(ri, ci) for ri in range(1, len(rows)) for ci, v in enumerate(rows[ri]) if not v]
chk("4 行 16 个单元格全部非空", not empty, f"空单元格 {empty}" if empty else "")

print()
print("【2】用户要求的两处修改")
full_col4 = "\n".join(rows[ri][3] for ri in range(1, len(rows)))
chk("已删除问法命中率一类表述",
    not any(k in full_col4 for k in ["命中", "24 句", "24句", "命中率", "100%"]))
chk("访谈表述仍强调由本人完成",
    "访谈过程由本人完成" in rows[1][3])
chk("工具列写明模型名",
    all("DeepSeek" in rows[ri][1] for ri in range(1, len(rows))),
    rows[1][1])

print()
print("【3】四行环节（模板给了 4 行）")
for ri in range(1, len(rows)):
    print(f"    行{ri}: {rows[ri][0]}  |  {len(rows[ri][2])} / {len(rows[ri][3])} 字")

print()
print("【4】模板原话与上下文")
texts = [p.text.strip() for p in d.paragraphs]
chk("模板说明句保留",
    "说明：AI提出但未被访谈证据确认的内容，不应直接作为正式需求。" in texts)
chk("第十一章标题在表之前",
    texts.index("十一、AI使用记录与人工确认") < texts.index("十二、V2.0结果与反思"))

print()
print("【5】结构与回归")
chk("表格数仍为 13", len(d.tables) == 13, f"{len(d.tables)} 张")
chk("图 8-1 在位", len(d.inline_shapes) == 1)
z = zipfile.ZipFile(P)
chk("ZIP 结构完好", z.testzip() is None)
chk("第五章管理员行仍是只读口径",
    "查看平台全部活动的报名与候补名单" in d.tables[6].rows[3].cells[1].text)
chk("第八章第 7 条仍在",
    any(p.text.strip().startswith("7. 名单查看范围：") for p in d.paragraphs))
t11 = d.tables[10]
chk("第十章测试表仍为 10 行（含 TEST-37）", len(t11.rows) == 10, f"{len(t11.rows)} 行")

print()
print("【6】第十二章仍为空（本轮不涉及）")
i12 = texts.index("十二、V2.0结果与反思")
i13 = texts.index("十三、组员确认")
seg = [x for x in texts[i12 + 1:i13] if x and not x.startswith(("1.", "2.", "3.", "4."))]
chk("第十二章仍无回答内容（待填）", len(seg) == 0,
    f"非问题段落 {seg[:2]}" if seg else "")

print()
print("=" * 62)
print(f"核验结果：{PASS} 项通过 / {FAIL} 项失败")
print("=" * 62)
sys.exit(0 if FAIL == 0 else 1)
