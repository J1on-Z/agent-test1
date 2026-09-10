"""开发启动入口：uvicorn 运行 FastAPI 应用。

生产部署建议：uvicorn app.main:app --host 0.0.0.0 --port 8000（去掉 --reload）
"""
import uvicorn

from app.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=settings.app_env == "dev",
    )
