# 校园活动管理系统 V1.0

软件工程实验一《基于工程意图的软件迭代开发》成果。1 人小组完成。

## 技术栈

- 后端：FastAPI（Python）+ SQLite（标准库 sqlite3）
- 前端：Vue 3（CDN，无构建步骤）+ 原生 HTML/CSS/JS
- 部署：同源部署（FastAPI 托管前端静态文件），本地运行

## 功能（对应需求 REQ-01~08）

| 角色 | 功能 |
|---|---|
| 所有用户 | 注册（学号/工号+姓名+密码+角色）、登录 |
| 学生 | 浏览活动广场、报名/取消报名、我的活动 |
| 教师 | 发布活动、管理自己发布的活动（编辑/取消）、查看报名名单 |
| 管理员 | 管理所有账号：查看列表、禁用/启用（禁用后无法登录）、删除账号 |
| 系统规则 | 名额上限、活动开始后不可报名、同人不可重复报名、密码哈希存储、管理员不可开放注册 |

## 本地启动

前置：Python 3.10+，安装依赖：

```bash
pip install fastapi uvicorn
```

项目根目录执行（首次会自动建库并写入演示数据）：

```bash
uvicorn backend.main:app --reload --port 8000
```

浏览器打开 http://127.0.0.1:8000 即可使用。
接口文档（FastAPI 自带）：http://127.0.0.1:8000/docs

## 演示账号

| 账号 | 姓名 | 角色 | 密码 |
|---|---|---|---|
| admin01 | 系统管理员 | 管理员 | Admin@123456 |
| teacher01 | 王老师 | 教师 | 123456 |
| student01 | 小明 | 学生 | 123456 |
| student02 | 小红 | 学生 | 123456 |

## 项目结构

```
backend/            FastAPI 后端
  main.py           应用入口（路由注册 + 静态托管）
  database.py       数据库层（建表 + 演示数据）
  auth.py           认证（密码哈希 + token）
  helpers.py        活动状态/字典转换公共函数
  routers/          业务路由（users/activities/registrations）
frontend/           Vue3 前端（index.html + app.js + style.css）
docs/               需求、工程意图、决策、设计文档
project-data/       实验过程数据记录
report/             实验报告工作副本
```

## 已知说明

- 认证 token 存于服务端内存，重启后需重新登录（实验规模简化，见 docs/04-软件设计.md 决策 4）；
- 演示数据库文件 `backend/activity.db` 自动生成，已加入 .gitignore 不提交。
