# -*- coding: utf-8 -*-
"""
候补链路端到端验证（R-01~R-05）。

覆盖：
  R-01 满员后进入候补队列（不再直接拒绝）
  R-02 候补按进入候补的时间先后排序
  R-03 报名状态区分（正式参加 / 候补中）
  R-04 正式报名取消后，空出的位置优先给候补最靠前的人
  R-05 候补退出后，排在其后的人依次前移
"""
import sys
from datetime import datetime, timedelta

import requests

sys.stdout.reconfigure(encoding='utf-8')
BASE = 'http://127.0.0.1:8000'
FMT = '%Y-%m-%d %H:%M'
results = []


def chk(tag, name, expect, actual, ok):
    results.append((tag, name, ok))
    print('  [%s] %-4s %-38s 期望=%s 实际=%s' % ('PASS' if ok else 'FAIL', tag, name, expect, actual))


def login(u, p='123456'):
    r = requests.post(BASE + '/api/login', json={'username': u, 'password': p}, timeout=10)
    if r.status_code != 200:
        return None
    return r.json()['token']


def H(tk):
    return {'Authorization': 'Bearer ' + tk}


# ---------------- 0. 准备测试账号 ----------------
print('=' * 84)
print('准备：注册 4 个测试学生账号')
print('=' * 84)
STUDENTS = ['v2stu1', 'v2stu2', 'v2stu3', 'v2stu4']
tokens = {}
for i, u in enumerate(STUDENTS, 1):
    requests.post(BASE + '/api/register', json={
        'username': u, 'name': '候补学生%d' % i, 'password': '123456', 'role': 'student'}, timeout=10)
    tokens[u] = login(u)
print('  账号就绪:', all(tokens.values()))

tk_teacher = login('teacher01')
print('  教师登录:', bool(tk_teacher))

# ---------------- 1. 发布容量 2 的活动 ----------------
s = (datetime.now() + timedelta(days=5)).strftime(FMT)
e = (datetime.now() + timedelta(days=5, hours=2)).strftime(FMT)
r = requests.post(BASE + '/api/activities', json={
    'title': '【V2.0】候补链路测试', 'description': '容量 2', 'location': '测试场地',
    'start_time': s, 'end_time': e, 'capacity': 2}, headers=H(tk_teacher), timeout=10)
aid = r.json().get('activity_id')
print('  活动已发布 id=%s' % aid)
print()

# ---------------- 2. 依次报名 ----------------
print('=' * 84)
print('【R-01 / R-03】满员后进入候补，报名状态区分')
print('=' * 84)
status = {}
for i, u in enumerate(STUDENTS, 1):
    rr = requests.post('%s/api/activities/%d/register' % (BASE, aid), headers=H(tokens[u]), timeout=10)
    body = rr.json()
    status[u] = body.get('reg_status')
    print('   学生%d 报名 → HTTP %d  %s  (reg_status=%s)'
          % (i, rr.status_code, body.get('message'), body.get('reg_status')))

chk('R-01', '第1人报名为正式参加', '正式参加', status['v2stu1'], status['v2stu1'] == '正式参加')
chk('R-01', '第2人报名为正式参加', '正式参加', status['v2stu2'], status['v2stu2'] == '正式参加')
chk('R-01', '第3人满员后进入候补', '候补中', status['v2stu3'], status['v2stu3'] == '候补中')
chk('R-01', '第4人同样进入候补', '候补中', status['v2stu4'], status['v2stu4'] == '候补中')
print()

# ---------------- 3. 名额口径 ----------------
print('=' * 84)
print('规则 1：名额口径（候补不占用正式名额）')
print('=' * 84)
d = requests.get('%s/api/activities/%d' % (BASE, aid), timeout=10).json()
chk('规则1', '已报名人数只算正式', 2, d['registered'], d['registered'] == 2)
chk('规则1', '候补人数为 2', 2, d['waitlisted'], d['waitlisted'] == 2)
chk('规则1', '剩余名额为 0', 0, d['remaining'], d['remaining'] == 0)

# ---------------- 4. 候补顺序 ----------------
print()
print('=' * 84)
print('【R-02】候补按进入候补的时间先后排序')
print('=' * 84)
lst = requests.get('%s/api/activities/%d/registrations' % (BASE, aid), headers=H(tk_teacher), timeout=10).json()
order = [(x['name'], x['reg_status_text'], x['queued_at']) for x in lst['students']]
for n, st, q in order:
    print('   %-12s %-8s queued_at=%s' % (n, st, q))
wl = [x for x in lst['students'] if x['reg_status'] == 'waitlisted']
chk('R-02', '候补队列按时间升序（先到先排）',
    '候补学生3 在 候补学生4 之前',
    '%s → %s' % (wl[0]['name'], wl[1]['name']) if len(wl) == 2 else '异常',
    len(wl) == 2 and wl[0]['name'] == '候补学生3' and wl[1]['name'] == '候补学生4')
chk('R-02', '两个候补都有 queued_at', '均有值',
    all(x['queued_at'] for x in wl), all(x['queued_at'] for x in wl))
chk('R-03', '教师名单含状态统计', '正式2/候补2/待审0',
    '%d/%d/%d' % (lst['confirmed_count'], lst['waitlisted_count'], lst['pending_count']),
    (lst['confirmed_count'], lst['waitlisted_count'], lst['pending_count']) == (2, 2, 0))
print()

# ---------------- 5. 递补 ----------------
print('=' * 84)
print('【R-04】正式报名取消后，空出的位置优先给候补最靠前的人')
print('=' * 84)
rr = requests.delete('%s/api/activities/%d/register' % (BASE, aid), headers=H(tokens['v2stu1']), timeout=10)
body = rr.json()
print('   学生1 取消报名 → HTTP %d  %s' % (rr.status_code, body.get('message')))
chk('R-04', '返回中被递补的用户已标记', '非空', body.get('promoted_user_id'), body.get('promoted_user_id') is not None)

mine3 = requests.get(BASE + '/api/my-activities', headers=H(tokens['v2stu3']), timeout=10).json()['activities']
st3 = [x for x in mine3 if x['id'] == aid][0]['reg_status']
mine4 = requests.get(BASE + '/api/my-activities', headers=H(tokens['v2stu4']), timeout=10).json()['activities']
st4 = [x for x in mine4 if x['id'] == aid][0]['reg_status']
chk('R-04', '候补最靠前者（学生3）转为正式参加', '正式参加', st3, st3 == '正式参加')
chk('R-04', '排队靠后者（学生4）仍在候补', '候补中', st4, st4 == '候补中')

d2 = requests.get('%s/api/activities/%d' % (BASE, aid), timeout=10).json()
chk('R-04', '正式人数维持容量上限', 2, d2['registered'], d2['registered'] == 2)
chk('R-04', '候补人数减为 1', 1, d2['waitlisted'], d2['waitlisted'] == 1)
print()

# ---------------- 6. 候补退出 ----------------
print('=' * 84)
print('【R-05】候补退出后，排在其后的人依次前移')
print('=' * 84)
rr = requests.delete('%s/api/activities/%d/register' % (BASE, aid), headers=H(tokens['v2stu4']), timeout=10)
print('   学生4 退出候补 → HTTP %d  %s' % (rr.status_code, rr.json().get('message')))
chk('R-05', '候补退出返回成功提示', '已退出候补', rr.json().get('message'), rr.status_code == 200)

d3 = requests.get('%s/api/activities/%d' % (BASE, aid), timeout=10).json()
chk('R-05', '退出候补不改变正式人数', 2, d3['registered'], d3['registered'] == 2)
chk('R-05', '候补人数减为 0', 0, d3['waitlisted'], d3['waitlisted'] == 0)

mine4b = requests.get(BASE + '/api/my-activities', headers=H(tokens['v2stu4']), timeout=10).json()['activities']
chk('R-05', '退出后该活动不再出现在其报名列表', 0,
    len([x for x in mine4b if x['id'] == aid]), len([x for x in mine4b if x['id'] == aid]) == 0)
print()

# ---------------- 7. 无候补时取消 ----------------
print('=' * 84)
print('异常分支：没有候补时取消，名额保持空缺')
print('=' * 84)
rr = requests.delete('%s/api/activities/%d/register' % (BASE, aid), headers=H(tokens['v2stu3']), timeout=10)
body = rr.json()
print('   学生3 取消报名 → HTTP %d  %s' % (rr.status_code, body.get('message')))
chk('R-04', '无候补时不产生递补', None, body.get('promoted_user_id'), body.get('promoted_user_id') is None)
d4 = requests.get('%s/api/activities/%d' % (BASE, aid), timeout=10).json()
chk('R-04', '正式人数减为 1，名额空缺', 1, d4['registered'], d4['registered'] == 1)
print()

# ---------------- 汇总 ----------------
print('=' * 84)
fail = [x for x in results if not x[2]]
print('候补链路验证：%d/%d 通过%s' % (len(results) - len(fail), len(results),
                                     '' if not fail else '  ｜ 失败：' + '；'.join(x[1] for x in fail)))
print('=' * 84)
print()
print('测试活动 id=%d（保留在库中便于前端演示，如需清理可删）' % aid)
