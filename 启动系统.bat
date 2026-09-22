@echo off
title Campus Activity System V2.0
rem 切到脚本所在目录（用 %~dp0，不写死绝对路径，换机器/换目录也能用）
cd /d "%~dp0"
echo ============================================
echo   校园活动管理系统 V2.0 正在启动...
echo   浏览器请访问: http://127.0.0.1:8000
echo   关闭本窗口即停止服务
echo ============================================
rem 需要 PATH 中可用的 python；未检测到时给出提示并退出
where python >nul 2>nul
if errorlevel 1 (
  echo [提示] 未检测到 python 命令，请先安装 Python 3.10+ 并在安装时勾选 Add Python to PATH
  pause
  exit /b 1
)
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
pause
