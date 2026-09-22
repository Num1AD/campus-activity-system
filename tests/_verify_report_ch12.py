"""
_verify_report_ch12.py —— 从磁盘读回报告，核对第十二章填写结果

核对点：
1. 四个问题各带 2 段回答，且没有残留空段落（模板给的空填写位是否被用满）
2. 每段内容长度合理、包含该问应有的要素
3. 文风自检（用户硬性要求）：破折号数量、套话与顺序词、重复修饰词
4. 结构回归：13 张表、图 8-1 在位、第十一章与第十三章内容未被影响
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
texts = [p.text.strip() for p in d.paragraphs]
i12 = next(i for i, t in enumerate(texts) if t.startswith("十二"))
i13 = next(i for i, t in enumerate(texts) if t.startswith("十三"))
body = texts[i12 + 1:i13]
questions = [t for t in body if t[:2] in ("1.", "2.", "3.", "4.")]
answers = [t for t in body if t and t[:2] not in ("1.", "2.", "3.", "4.")]
ch12 = "\n".join(body)

print("【1】结构与完整性")
chk("四个问题都在", len(questions) == 4, " / ".join(q[:14] for q in questions))
chk("四问共 8 段回答（模板每问留 2 段）", len(answers) == 8, f"{len(answers)} 段")
chk("无残留空段落", not any(t == "" for t in body))
chk("每段长度 100~160 字（按本人要求压缩后）",
    all(100 <= len(a) <= 160 for a in answers),
    f"最短 {min(len(a) for a in answers)} / 最长 {max(len(a) for a in answers)} 字")
chk("全章合计不超过 1200 字", len(ch12) < 1200, f"{len(ch12)} 字（不含标题与问题）")

print()
print("【2】各问要素")
q1 = "\n".join(answers[0:2])
q2 = "\n".join(answers[2:4])
q3 = "\n".join(answers[4:6])
q4 = "\n".join(answers[6:8])
chk("第 1 问写到候补、审核、管理员三类变化",
    all(k in q1 for k in ["候补", "审核", "管理员"]))
chk("第 1 问写到数据层与回归",
    "报名状态" in q1 and "回归" in q1)
chk("第 2 问写到候补链路的追问",
    "追问" in q2 and "候补" in q2 and "排序依据" in q2)
chk("第 2 问写到跨角色核对",
    "跨角色" in q2 and "教师" in q2 and "管理员" in q2)
chk("第 3 问写到名额统计口径",
    "已报名人数" in q3 and "占用" in q3)
chk("第 3 问写到候补排序依据与事务",
    "进入候补时间" in q3 and "同一事务" in q3)
chk("第 4 问写到角色差异与需求出处",
    "不同侧面" in q4 and "出处" in q4)

print()
print("【3】文风自检（用户硬性要求）")
dash = ch12.count("——")
chk("第十二章无长破折号", dash == 0, f"{dash} 处")
banned = ["综上所述", "首先", "其次", "机遇与挑战", "赋能", "闭环", "抓手", "维度"]
hit = [w for w in banned if w in ch12]
chk("无套话与列举式顺序词", not hit, f"命中 {hit}" if hit else "")
chk("「此外」不超过 1 次", ch12.count("此外") <= 1, f"{ch12.count('此外')} 次")
chk("无口语化词", not any(w in ch12 for w in ["搞", "弄", "说白了", "其实"]))
colloquial = ["拿去问", "才拿到", "最省事", "不是一回事", "按旧习惯", "拿到一半", "往下追问才问到"]
hit2 = [w for w in colloquial if w in ch12]
chk("上一版的口语化说法已清除", not hit2, f"残留 {hit2}" if hit2 else "")

print()
print("【4】结构回归")
chk("表格数仍为 13", len(d.tables) == 13, f"{len(d.tables)} 张")
chk("图 8-1 在位", len(d.inline_shapes) == 1)
z = zipfile.ZipFile(P)
chk("ZIP 结构完好", z.testzip() is None)
t_ai = d.tables[11]
chk("第十一章 AI 记录表仍完整",
    all(t_ai.rows[r].cells[c].text.strip() for r in range(1, 5) for c in range(4)))
chk("第五章管理员行仍是只读口径",
    "查看平台全部活动的报名与候补名单" in d.tables[6].rows[3].cells[1].text)
chk("第八章第 7 条仍在",
    any(t.startswith("7. 名单查看范围：") for t in texts))
chk("第十三章确认句仍在",
    any("本人确认本报告所记录的访谈" in t for t in texts))

print()
print("【5】一致性（与第八章口径对照）")
chk("第十二章的报名三态与第八章一致",
    ("候补中" in ch12 or "候补队列" in ch12) and "待审核" in ch12 and "正式参加" in ch12)
chk("未出现「已拒绝」这类第八章未定义的状态", "已拒绝" not in ch12)
chk("未出现四种活动状态的说法",
    "已满" not in ch12 or "被判为已满" in ch12)

print()
print("=" * 62)
print(f"核验结果：{PASS} 项通过 / {FAIL} 项失败")
print("=" * 62)
sys.exit(0 if FAIL == 0 else 1)
