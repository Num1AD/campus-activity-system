"""
main.py —— FastAPI 应用入口

启动方式（在项目根目录执行）：
    uvicorn backend.main:app --reload --port 8000
或：
    python -m backend.main

应用组成：
1. 注册三个业务路由（用户/活动/报名），统一挂载在 /api 前缀
2. 托管前端静态文件（同源部署，docs/04-软件设计.md 4.4 决策 5）
3. 启动时初始化数据库（建表 + 演示数据）
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.database import init_db
from backend.routers import activities, registrations, users

# 前端静态目录：项目根/frontend
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动时初始化数据库（建表 + 首次写入演示数据）。"""
    init_db()
    yield


app = FastAPI(
    title="校园活动管理系统 API",
    description="软件工程实验一：校园活动管理系统 V1.0（FastAPI + SQLite + Vue3）",
    version="1.0.0",
    lifespan=lifespan,
)

# 注册业务路由（统一 /api 前缀）
app.include_router(users.router)
app.include_router(activities.router)
app.include_router(registrations.router)


@app.get("/api/health", summary="健康检查")
def health():
    """接口连通性检查。"""
    return {"status": "ok", "service": "campus-activity-system", "version": "1.0.0"}


# 托管前端静态文件（需放在 API 路由之后注册，避免吞掉 /api 请求）
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    # 直接运行入口：python -m backend.main
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)
