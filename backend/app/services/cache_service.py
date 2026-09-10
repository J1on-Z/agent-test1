"""语义缓存：SQLite 持久化 + 查询向量余弦相似度匹配（自研，无 Redis 依赖）。

设计要点：
- 记忆感知：缓存 key 包含 memory_hash（会话历史摘要的 hash），
  多轮对话中相同问题不同上下文不会互相污染
- TTL 过期 + 写入时顺带清理过期条目
- 命中返回完整答案与引文（零 LLM 调用，TTFT < 50ms）
生产环境替换方案：Redis Vector / GPTCache 共享缓存（README 说明）。
"""
import logging
from datetime import timedelta

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import SemanticCacheEntry
from app.models.common import utcnow

logger = logging.getLogger(__name__)


def _cosine(a: list[float], b: list[float]) -> float:
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


async def lookup_exact(db: AsyncSession, question: str, memory_hash: str) -> dict | None:
    """精确匹配快速路径：同文本同上下文直接命中（无需查询向量，<20ms）。

    置于语义匹配之前调用，覆盖「重复提问」这一最常见缓存场景。
    """
    if not settings.semantic_cache_enabled:
        return None
    await cleanup_expired(db)
    row = await db.scalar(
        select(SemanticCacheEntry)
        .where(
            SemanticCacheEntry.query_text == question,
            SemanticCacheEntry.memory_hash == memory_hash,
            SemanticCacheEntry.expires_at > utcnow(),
        )
        .order_by(SemanticCacheEntry.id.desc())
    )
    if row is None:
        return None
    row.hit_count += 1
    await db.commit()
    logger.info("缓存精确命中（累计 %d 次）", row.hit_count)
    return {"answer": row.answer, "citations": row.citations or []}


async def lookup(db: AsyncSession, query_embedding: list[float], memory_hash: str) -> dict | None:
    """语义匹配：相似问题（换措辞）命中，返回 {answer, citations}；未命中返回 None。"""
    if not settings.semantic_cache_enabled:
        return None
    await cleanup_expired(db)
    rows = list(
        (
            await db.scalars(
                select(SemanticCacheEntry).where(
                    SemanticCacheEntry.memory_hash == memory_hash,
                    SemanticCacheEntry.expires_at > utcnow(),
                )
            )
        ).all()
    )
    best, best_score = None, settings.semantic_cache_threshold
    for row in rows:
        score = _cosine(query_embedding, row.query_embedding or [])
        if score > best_score:
            best, best_score = row, score
    if best is None:
        return None
    best.hit_count += 1
    await db.commit()
    logger.info("语义缓存命中（相似度 %.3f，累计命中 %d 次）", best_score, best.hit_count)
    return {"answer": best.answer, "citations": best.citations or []}


async def store(
    db: AsyncSession,
    question: str,
    query_embedding: list[float],
    memory_hash: str,
    answer: str,
    citations: list,
) -> None:
    """写入缓存条目（同问题同上下文重复存储时先删旧）。"""
    if not settings.semantic_cache_enabled or not answer:
        return
    # 精确同文本且同上下文 → 覆盖
    await db.execute(
        delete(SemanticCacheEntry).where(
            SemanticCacheEntry.query_text == question,
            SemanticCacheEntry.memory_hash == memory_hash,
        )
    )
    db.add(
        SemanticCacheEntry(
            query_text=question,
            query_embedding=query_embedding,
            memory_hash=memory_hash,
            answer=answer,
            citations=citations,
            expires_at=utcnow() + timedelta(hours=settings.semantic_cache_ttl_hours),
        )
    )
    await db.commit()


async def cleanup_expired(db: AsyncSession) -> None:
    """删除过期条目（每次查找时顺带执行，代价一条 DELETE）。"""
    await db.execute(
        delete(SemanticCacheEntry).where(SemanticCacheEntry.expires_at <= utcnow())
    )
    await db.commit()
