"""FastAPI 应用工厂与启动钩子。

启动流程：日志 → 建表 → 种子管理员 → （P2 起）初始化向量库/BM25 → 对外服务。
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api import api_router
from app.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging_config import setup_logging
from app.core.rate_limit import limiter
from app.database import Base, engine

logger = logging.getLogger(__name__)


async def _init_runtime_components() -> None:
    """初始化依赖外部服务的运行时组件（向量库/BM25），失败仅告警不阻断启动。"""
    try:
        from app.services.ingest.pipeline import mark_stale_jobs_failed
        from app.services.retrieval.bm25 import get_bm25_index
        from app.services.retrieval.vector_store import load_index

        await load_index()  # 向量索引装载（SQLite → numpy 内存矩阵）
        await get_bm25_index()  # 从 SQLite chunks 重建内存 BM25 索引
        mark_stale_jobs_failed()  # 进程重启遗留的进行中任务置为失败
    except Exception as e:  # noqa: BLE001
        logger.warning("运行时组件初始化失败（不影响登录等基础功能）: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    # 建表（import app.models 确保模型已注册）
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.services.auth_service import ensure_admin_user

    await ensure_admin_user()
    await _init_runtime_components()
    logger.info("应用启动完成：%s", settings.app_name)
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="电商 RAG 知识库智能问答系统",
        description="基于 LangChain/LangGraph 的企业级知识库问答系统（毕设）",
        version="1.0.0",
        lifespan=lifespan,
    )
    # CORS：开发期允许 Vite dev server 跨域
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # 限流中间件 + 429 统一错误格式
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api")
    return app


app = create_app()
