/*
 * app.js —— 前端应用逻辑（Vue 3 Options API）
 *
 * 职责：
 * 1. 封装 API 调用（自动附带 localStorage 中的 token）
 * 2. 登录 / 注册 / 退出
 * 3. 活动广场：浏览活动、报名 / 取消报名
 * 4. 我的活动：学生查看报名状态（含候补与待审核）；教师发布 / 编辑 / 取消活动、审核报名、查看名单
 * 5. 账号管理：系统管理员查看账号与停用/恢复（V2.0 新增）
 *
 * V2.0 变化（对应报告第六章 US-01~US-08）：
 * - 学生报名状态分「待审核 / 正式参加 / 候补中」三种，按钮文案随之变化
 * - 满员活动报名按钮提示「进入候补」，不再是简单的"不可报名"
 * - 教师发布/编辑活动时可设置是否需要审核与参加资格
 * - 教师报名名单按状态分组，待审核的报名可直接通过或拒绝
 *
 * 认证方案（与后端一致）：登录返回 token，存入 localStorage（键 cas_token）；
 * 退出登录会先调用 /api/logout 让服务端注销该 token，再清除本地记录。
 */

// Vue 全局对象来自 index.html 引入的本地 vendor
const { createApp } = Vue;

// ---------------------------------------------------------------
// API 封装：统一处理 token 与错误
// ---------------------------------------------------------------
async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  // 已登录则自动附带 token
  const token = localStorage.getItem('cas_token');
  if (token) headers['Authorization'] = `Bearer ${token}`;

  let resp;
  try {
    resp = await fetch(path, { ...options, headers });
  } catch {
    // fetch 网络层失败（服务器未启动/已停止）——给出明确提示而不是静默无反应
    throw new Error('无法连接服务器，请确认系统已启动（双击"启动系统.bat"）');
  }
  const data = await resp.json().catch(() => ({}));

  // 非 2xx 时抛出后端返回的错误信息，由调用方提示用户
  if (!resp.ok) {
    throw new Error(data.detail || `请求失败（${resp.status}）`);
  }
  return data;
}

// ---------------------------------------------------------------
// Vue 应用
// ---------------------------------------------------------------
const app = createApp({
  data() {
    return {
      view: 'list',              // 当前视图：list=活动广场，mine=我的活动，admin=账号管理
      user: null,                // 当前登录用户（null=未登录）
      activities: [],            // 活动广场列表
      mineActivities: [],        // 我的活动列表
      myRegMap: {},              // 我的报名状态映射 {活动id: {code, text, queued_at}}（学生）
      // 登录/注册弹层
      authModal: { show: false, mode: 'login' },
      authForm: { name: '', username: '', password: '', role: 'student' },
      // 发布活动弹层
      publishModal: false,
      publishForm: {
        title: '', description: '', location: '', start_time: '', end_time: '', capacity: 20,
        require_review: false, eligibility: '',
      },
      // 编辑活动弹层（教师，REQ-04）
      editModal: false,
      editForm: {
        id: null, title: '', description: '', location: '', start_time: '', end_time: '', capacity: 20,
        require_review: false, eligibility: '',
      },
      // 报名名单弹层（教师）
      studentListModal: false,
      studentList: [],
      currentAct: {},
      // 账号管理（管理员）
      adminUsers: [],
      adminSummary: { total: 0, disabled: 0 },
    };
  },

  async mounted() {
    // 页面加载：尝试恢复登录态，并拉取活动列表
    await this.restoreSession();
    await this.loadActivities();
  },

  computed: {
    /* 教师名单按报名状态分组（顺序：待审核 → 正式参加 → 候补中，与后端返回一致） */
    pendingList() {
      return this.studentList.filter((s) => s.reg_status === 'pending');
    },
    confirmedList() {
      return this.studentList.filter((s) => s.reg_status === 'confirmed');
    },
    waitlistedList() {
      return this.studentList.filter((s) => s.reg_status === 'waitlisted');
    },
  },

  methods: {
    /* ---------- 角色显示 ---------- */
    roleText(role) {
      // 角色名转中文显示（顶部徽章）
      return { student: '学生', teacher: '教师', admin: '管理员' }[role] || role;
    },

    /* ---------- 视图切换 ---------- */
    async switchView(v) {
      this.view = v;
      // "我的活动"与"账号管理"需登录
      if (v === 'mine' || v === 'admin') {
        if (!this.user) {
          this.openAuth('login');
          this.view = 'list';
          return;
        }
        if (v === 'mine') await this.loadMine();
        if (v === 'admin') await this.loadAdminUsers();
      }
    },

    /* ---------- 会话管理 ---------- */
    async restoreSession() {
      const token = localStorage.getItem('cas_token');
      if (!token) return;
      try {
        // 通过 /api/me 校验 token 是否仍有效
        this.user = await api('/api/me');
        await this.loadActivities();
      } catch {
        // token 已失效：直接清理本地状态（无需再请求注销接口）
        localStorage.removeItem('cas_token');
        this.user = null;
        this.view = 'list';
      }
    },

    openAuth(mode) {
      this.authModal = { show: true, mode };
      this.authForm = { name: '', username: '', password: '', role: 'student' };
    },

    async submitAuth() {
      const f = this.authForm;
      try {
        if (this.authModal.mode === 'register') {
          // 先注册再自动登录
          await api('/api/register', {
            method: 'POST',
            body: JSON.stringify({ username: f.username, name: f.name, password: f.password, role: f.role }),
          });
        }
        // 登录拿 token
        const data = await api('/api/login', {
          method: 'POST',
          body: JSON.stringify({ username: f.username, password: f.password }),
        });
        localStorage.setItem('cas_token', data.token);
        this.user = data.user;
        this.authModal.show = false;
        alert('登录成功，欢迎 ' + data.user.name);
        await this.loadActivities();
      } catch (e) {
        // 任何失败都明确提示（如服务器未启动、用户名密码错误）
        alert(e.message || '操作失败，请稍后重试');
      }
    },

    async logout() {
      // 先通知服务端注销 token；失败也不阻塞本地清理，避免出现"退不出去"
      try {
        await api('/api/logout', { method: 'POST' });
      } catch {
        // 网络异常或 token 已失效：忽略，继续清理本地状态
      }
      localStorage.removeItem('cas_token');
      this.user = null;
      this.view = 'list';
    },

    /* ---------- 活动数据 ---------- */
    async loadActivities() {
      // 活动广场列表；若已登录同时维护"我的报名状态"映射
      const data = await api('/api/activities');
      this.activities = data.activities;
      await this.loadMine();
    },

    /* ---------- 我的活动数据 ---------- */
    async loadMine() {
      // 学生：维护报名状态映射；教师：我发布的活动；管理员：不参与活动业务
      if (!this.user || this.user.role !== 'student') {
        this.myRegMap = {};
        this.mineActivities = this.user && this.user.role === 'teacher'
          ? (await api('/api/my-activities')).activities
          : [];
        return;
      }
      const data = await api('/api/my-activities');
      this.mineActivities = data.activities;
      // 报名状态三态（待审核 / 正式参加 / 候补中），按钮与标签据此渲染
      const map = {};
      for (const a of data.activities) {
        map[a.id] = {
          code: a.reg_status_code,
          text: a.reg_status,
          queued_at: a.reg_queued_at,
        };
      }
      this.myRegMap = map;
    },

    /* ---------- 活动广场：报名/取消 ---------- */
    myReg(act) {
      // 当前用户对该活动的报名状态（null = 未报名）
      if (!this.user || this.user.role !== 'student') return null;
      return this.myRegMap[act.id] || null;
    },

    regBtnText(act) {
      // 报名按钮文案：按本人报名状态与活动名额情况区分
      if (!this.user) return '登录后报名';
      if (this.user.role !== 'student') return '不可报名';
      const reg = this.myReg(act);
      if (reg) {
        // 已报名：按状态提供对应操作（撤回申请 / 退出候补 / 取消报名）
        if (reg.code === 'pending') return '撤回申请';
        if (reg.code === 'waitlisted') return '退出候补';
        return '取消报名';
      }
      if (act.status !== '报名中') return '不可报名';
      // 满员时明确提示会进入候补，而不是让用户以为报名失败（US-01）
      return act.remaining > 0 ? '报名' : '报名（进入候补）';
    },

    regBtnDisabled(act) {
      // 已报名的记录随时可撤回/退出/取消；未报名时仅"报名中"且未截止可操作
      if (!this.user || this.user.role !== 'student') return true;
      if (this.myReg(act)) return false;
      return act.status !== '报名中';
    },

    async handleRegister(act) {
      // 未登录点报名 → 提示并弹出登录框
      if (!this.user) {
        alert('报名需要先登录');
        this.openAuth('login');
        return;
      }
      // 学生可报名/取消；其他角色点报名按钮无意义，直接忽略
      if (this.user.role !== 'student') return;

      const reg = this.myReg(act);
      try {
        if (reg) {
          await api(`/api/activities/${act.id}/register`, { method: 'DELETE' });
          alert({ pending: '已撤回报名申请', waitlisted: '已退出候补' }[reg.code] || '已取消报名');
        } else {
          const r = await api(`/api/activities/${act.id}/register`, { method: 'POST' });
          // 后端返回真实结果：报名成功 / 进入候补 / 等待审核
          alert(r.message || '报名成功');
        }
        await this.loadActivities();
      } catch (e) {
        alert(e.message);
      }
    },

    async unregister(act) {
      const reg = this.myReg(act);
      try {
        await api(`/api/activities/${act.id}/register`, { method: 'DELETE' });
        alert({ pending: '已撤回报名申请', waitlisted: '已退出候补' }[reg && reg.code] || '已取消报名');
        await this.loadMine();
        await this.loadActivities();
      } catch (e) {
        alert(e.message);
      }
    },

    /* ---------- 教师：发布 / 取消 / 名单 ---------- */
    openPublish() {
      // 打开发布表单：默认开始时间为 7 天后，结束时间比开始晚 2 小时。
      // 两者若同为默认值会被后端以"结束时间必须晚于开始时间"拒绝，故默认值必须错开。
      const fmt = (d) => {
        const pad = (n) => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
      };
      const start = new Date(Date.now() + 7 * 24 * 3600 * 1000);
      const end = new Date(start.getTime() + 2 * 3600 * 1000);
      this.publishForm = {
        title: '', description: '', location: '',
        start_time: fmt(start), end_time: fmt(end), capacity: 20,
        require_review: false, eligibility: '',
      };
      this.publishModal = true;
    },

    async submitPublish() {
      const f = this.publishForm;
      try {
        // datetime-local 的值为 "YYYY-MM-DDTHH:MM"，转成后端格式 "YYYY-MM-DD HH:MM"
        await api('/api/activities', {
          method: 'POST',
          body: JSON.stringify({
            title: f.title,
            description: f.description,
            location: f.location,
            start_time: f.start_time.replace('T', ' '),
            end_time: f.end_time.replace('T', ' '),
            capacity: f.capacity,
            // V2.0：是否审核由教师按活动决定；资格条件用于向学生说明参加要求
            require_review: !!f.require_review,
            eligibility: f.eligibility || '',
          }),
        });
        alert('发布成功');
        this.publishModal = false;
        await this.loadMine();
        await this.loadActivities();
      } catch (e) {
        alert(e.message);
      }
    },

    /* ---------- 教师：编辑活动（REQ-04） ---------- */
    openEdit(act) {
      // 用活动当前值填充编辑表单；datetime-local 需要 "YYYY-MM-DDTHH:MM" 形式
      this.editForm = {
        id: act.id,
        title: act.title,
        description: act.description || '',
        location: act.location,
        start_time: (act.start_time || '').replace(' ', 'T'),
        end_time: (act.end_time || '').replace(' ', 'T'),
        capacity: act.capacity,
        require_review: !!act.require_review,
        eligibility: act.eligibility || '',
      };
      this.editModal = true;
    },

    async submitEdit() {
      const f = this.editForm;
      try {
        // datetime-local 的值为 "YYYY-MM-DDTHH:MM"，转成后端格式 "YYYY-MM-DD HH:MM"
        await api(`/api/activities/${f.id}`, {
          method: 'PUT',
          body: JSON.stringify({
            title: f.title,
            description: f.description,
            location: f.location,
            start_time: f.start_time.replace('T', ' '),
            end_time: f.end_time.replace('T', ' '),
            capacity: f.capacity,
            require_review: !!f.require_review,
            eligibility: f.eligibility || '',
          }),
        });
        alert('修改成功');
        this.editModal = false;
        await this.loadMine();
        await this.loadActivities();
      } catch (e) {
        alert(e.message);
      }
    },

    async cancelActivity(act) {
      if (!confirm(`确定取消活动「${act.title}」吗？取消后学生将无法报名。`)) return;
      try {
        await api(`/api/activities/${act.id}/cancel`, { method: 'POST' });
        alert('活动已取消');
        await this.loadMine();
        await this.loadActivities();
      } catch (e) {
        alert(e.message);
      }
    },

    async viewStudents(act) {
      try {
        const data = await api(`/api/activities/${act.id}/registrations`);
        this.currentAct = act;
        this.studentList = data.students;
        this.studentListModal = true;
      } catch (e) {
        alert(e.message);
      }
    },

    /* ---------- 教师：审核报名（R-06 / R-07） ---------- */
    async review(student, approve) {
      const verb = approve ? '通过' : '拒绝';
      if (!confirm(`确定${verb}「${student.name}」的报名申请吗？`)) return;
      try {
        const r = await api(
          `/api/activities/${this.currentAct.id}/registrations/${student.id}/review`,
          { method: 'POST', body: JSON.stringify({ approve }) },
        );
        // 后端会说明通过后是正式参加还是进入候补，直接展示结果
        alert(r.message);
        await this.viewStudents(this.currentAct);
        await this.loadMine();
        await this.loadActivities();
      } catch (e) {
        alert(e.message);
      }
    },

    /* ---------- 管理员：账号管理（R-08） ---------- */
    async loadAdminUsers() {
      const data = await api('/api/admin/users');
      this.adminUsers = data.users;
      this.adminSummary = { total: data.total, disabled: data.disabled };
    },

    async toggleUser(u) {
      // is_active 取反：当前可用 → 停用；当前停用 → 恢复
      const next = !u.is_active;
      const verb = next ? '恢复' : '停用';
      if (!confirm(`确定${verb}账号「${u.name}（${u.username}）」吗？`)) return;
      try {
        const r = await api(`/api/admin/users/${u.id}/status`, {
          method: 'POST',
          body: JSON.stringify({ is_active: next }),
        });
        alert(r.message);
        await this.loadAdminUsers();
      } catch (e) {
        alert(e.message);
      }
    },
  },
});

app.mount('#app');
