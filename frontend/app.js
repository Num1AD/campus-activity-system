/*
 * app.js —— 前端应用逻辑（Vue 3 Options API）
 *
 * 职责：
 * 1. 封装 API 调用（自动附带 localStorage 中的 token）
 * 2. 登录 / 注册 / 退出
 * 3. 活动广场：浏览活动、报名 / 取消报名
 * 4. 我的活动：学生查看已报名；教师发布 / 取消活动 / 查看报名名单
 *
 * 认证方案（与后端一致）：登录返回 token，存入 localStorage（键 cas_token）。
 */

// Vue 全局对象来自 index.html 引入的 CDN
const { createApp } = Vue;

// ---------------------------------------------------------------
// API 封装：统一处理 token 与错误
// ---------------------------------------------------------------
async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  // 已登录则自动附带 token
  const token = localStorage.getItem('cas_token');
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const resp = await fetch(path, { ...options, headers });
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
      view: 'list',              // 当前视图：list=活动广场，mine=我的活动
      user: null,                // 当前登录用户（null=未登录）
      activities: [],            // 活动广场列表
      mineActivities: [],        // 我的活动列表
      myRegIds: new Set(),       // 我报名过的活动 id 集合（用于按钮态）
      // 登录/注册弹层
      authModal: { show: false, mode: 'login' },
      authForm: { name: '', username: '', password: '', role: 'student' },
      // 发布活动弹层
      publishModal: false,
      publishForm: { title: '', description: '', location: '', start_time: '', end_time: '', capacity: 20 },
      // 报名名单弹层
      studentListModal: false,
      studentList: [],
      currentAct: {},
    };
  },

  async mounted() {
    // 页面加载：尝试恢复登录态，并拉取活动列表
    await this.restoreSession();
    await this.loadActivities();
  },

  methods: {
    /* ---------- 视图切换 ---------- */
    async switchView(v) {
      this.view = v;
      // 进入"我的活动"需登录
      if (v === 'mine') {
        if (!this.user) {
          this.openAuth('login');
          this.view = 'list';
          return;
        }
        await this.loadMine();
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
        // token 失效则清除
        this.logout();
      }
    },

    openAuth(mode) {
      this.authModal = { show: true, mode };
      this.authForm = { name: '', username: '', password: '', role: 'student' };
    },

    async submitAuth() {
      const f = this.authForm;
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
    },

    logout() {
      localStorage.removeItem('cas_token');
      this.user = null;
      this.view = 'list';
    },

    /* ---------- 活动数据 ---------- */
    async loadActivities() {
      // 活动广场列表；若已登录同时维护"我报过哪些"集合
      const data = await api('/api/activities');
      this.activities = data.activities;
      if (this.user) {
        const mine = await api('/api/my-activities');
        this.mineActivities = mine.activities;
        this.myRegIds = new Set(
          this.user.role === 'student'
            ? this.mineActivities.map((a) => a.id)
            : []  // 教师无报名概念
        );
      }
    },

    async loadMine() {
      const data = await api('/api/my-activities');
      this.mineActivities = data.activities;
    },

    /* ---------- 活动广场：报名/取消 ---------- */
    regState(act) {
      // 判断当前用户对该活动的报名状态（用于按钮文案）
      return this.user && this.user.role === 'student' && this.myRegIds.has(act.id)
        ? 'registered' : 'none';
    },

    async handleRegister(act) {
      // 未登录点报名 → 提示并弹出登录框
      if (!this.user) {
        alert('报名需要先登录');
        this.openAuth('login');
        return;
      }
      // 学生可报名/取消；教师点报名按钮无意义，直接忽略
      if (this.user.role !== 'student') return;

      try {
        if (this.regState(act) === 'registered') {
          await api(`/api/activities/${act.id}/register`, { method: 'DELETE' });
          alert('已取消报名');
        } else {
          await api(`/api/activities/${act.id}/register`, { method: 'POST' });
          alert('报名成功');
        }
        await this.loadActivities();
      } catch (e) {
        alert(e.message);
      }
    },

    async unregister(act) {
      try {
        await api(`/api/activities/${act.id}/register`, { method: 'DELETE' });
        alert('已取消报名');
        await this.loadMine();
        await this.loadActivities();
      } catch (e) {
        alert(e.message);
      }
    },

    /* ---------- 教师：发布 / 取消 / 名单 ---------- */
    openPublish() {
      // 打开发布表单，默认时间建议为 7 天后
      const d = new Date(Date.now() + 7 * 24 * 3600 * 1000);
      const pad = (n) => String(n).padStart(2, '0');
      const dt = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
      this.publishForm = { title: '', description: '', location: '', start_time: dt, end_time: dt, capacity: 20 };
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
  },
});

app.mount('#app');
