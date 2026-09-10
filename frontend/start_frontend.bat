@echo off
rem 电商 RAG 知识库智能问答系统 - 前端启动脚本
chcp 65001 >nul
cd /d %~dp0

if not exist node_modules (
    echo [信息] 首次运行，安装依赖中...
    call npm install
)

npm run dev
pause
