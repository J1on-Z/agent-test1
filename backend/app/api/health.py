"""健康自检：DB / DashScope 连通性（GET /models 不消耗 token 额度）。"""
import logging

import httpx
from fastapi import APIRouter
from sqlalchemy import text

from app.config import settings
from app.database import AsyncSessionLocal

router = APIRouter(tags=["系统"])
logger = logging.getLogger(__name__)


async def _check_db() -> dict:
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        logger.warning("数据库自检失败: %s", e)
        return {"ok": False, "error": str(e)}


async def _check_dashscope() -> dict:
    if not settings.dashscope_api_key:
        return {"ok": False, "error": "未配置 DASHSCOPE_API_KEY"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.dashscope_base_url}/models",
                headers={"Authorization": f"Bearer {settings.dashscope_api_key}"},
            )
        ok = resp.status_code in (200, 201)
        return {"ok": ok, "status": resp.status_code, "detail": "" if ok else resp.text[:200]}
    except Exception as e:  # noqa: BLE001
        logger.warning("DashScope 自检失败: %s", e)
        return {"ok": False, "error": str(e)}


def _check_vector_store() -> dict:
    """向量库自检：内存索引与 DB 行数一致性。"""
    try:
        from app.services.retrieval import vector_store

        mem = vector_store.collection_count()
        db_v = vector_store.db_vector_count()
        db_c = vector_store.db_chunk_count()
        return {
            "ok": mem == db_v == db_c,
            "memory_vectors": mem,
            "db_vectors": db_v,
            "db_chunks": db_c,
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


@router.get("/health")
async def health():
    """连通性自检，供启动验证与部署探活。"""
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "database": await _check_db(),
        "vector_store": _check_vector_store(),
        "dashscope": await _check_dashscope(),
    }
