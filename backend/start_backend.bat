@echo off
rem 电商 RAG 知识库智能问答系统 - 后端启动脚本
chcp 65001 >nul
set PYTHONUTF8=1
cd /d %~dp0

if not exist .venv\Scripts\python.exe (
    echo [错误] 未找到虚拟环境，请先执行：
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

.venv\Scripts\python.exe run.py
pause
