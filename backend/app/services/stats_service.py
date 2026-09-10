"""统计服务：request_logs 等聚合 → 管理端仪表盘数据（性能指标的来源）。"""
import logging
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    Conversation,
    Document,
    Message,
    RequestLog,
    SemanticCacheEntry,
    User,
)
from app.models.common import utcnow
from app.utils.text import count_tokens_approx

logger = logging.getLogger(__name__)


def _percentile(sorted_values: list[float], p: float) -> float | None:
    """最近邻百分位（数据量小，Python 侧计算）。"""
    if not sorted_values:
        return None
    idx = min(int(len(sorted_values) * p), len(sorted_values) - 1)
    return sorted_values[idx]


def _last_days(days: int) -> list:
    """最近 N 天的 (date 对象, 显示标签)。"""
    today = utcnow().date()
    out = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        out.append((d, d.strftime("%m-%d")))
    return out


async def overview(db: AsyncSession) -> dict:
    user_count = await db.scalar(select(func.count(User.id)))
    conversation_count = await db.scalar(select(func.count(Conversation.id)))
    message_count = await db.scalar(select(func.count(Message.id)))
    document_count = await db.scalar(select(func.count(Document.id)))
    ready_documents = await db.scalar(
        select(func.count(Document.id)).where(Document.status == "ready")
    )

    log_agg = (
        await db.execute(
            select(
                func.coalesce(func.sum(RequestLog.total_tokens), 0),
                func.coalesce(func.sum(RequestLog.prompt_tokens), 0),
                func.coalesce(func.sum(RequestLog.completion_tokens), 0),
                func.coalesce(func.avg(RequestLog.latency_ms), 0),
                func.count(RequestLog.id),
            )
        )
    ).one()
    total_tokens, prompt_tokens, completion_tokens, avg_latency_ms, log_count = log_agg

    latency_rows = list((await db.scalars(select(RequestLog.latency_ms).where(RequestLog.latency_ms.isnot(None)))).all())
    latency_sorted = sorted(latency_rows)

    today = utcnow().date()
    active_users_today = await db.scalar(
        select(func.count(func.distinct(RequestLog.user_id))).where(
            func.date(RequestLog.created_at) == str(today)
        )
    )

    # 缓存指标：命中次数与估算节省 token（按缓存答案长度 × 命中次数）
    cache_rows = list(
        (await db.execute(select(SemanticCacheEntry.hit_count, SemanticCacheEntry.answer))).all()
    )
    cache_hits = sum(h for h, _ in cache_rows)
    saved_tokens = sum(h * count_tokens_approx(a) for h, a in cache_rows)
    cache_hit_rate = round(cache_hits / (log_count + cache_hits) * 100, 1) if (log_count + cache_hits) else 0

    cost = (
        prompt_tokens / 1_000_000 * settings.price_input_per_1m
        + completion_tokens / 1_000_000 * settings.price_output_per_1m
    )

    return {
        "user_count": user_count,
        "active_users_today": active_users_today or 0,
        "conversation_count": conversation_count,
        "message_count": message_count,
        "document_count": document_count,
        "ready_documents": ready_documents,
        "total_tokens": int(total_tokens),
        "estimated_cost_yuan": round(cost, 4),
        "cache_hit_rate": cache_hit_rate,
        "cache_hits": cache_hits,
        "saved_tokens": int(saved_tokens),
        "avg_latency_ms": int(avg_latency_ms or 0),
        "p50_latency_ms": int(_percentile(latency_sorted, 0.5) or 0),
        "p95_latency_ms": int(_percentile(latency_sorted, 0.95) or 0),
    }


async def daily(db: AsyncSession, days: int = 14) -> dict:
    """按天聚合：问答数与活跃用户。"""
    date_range = _last_days(days)
    rows = (
        await db.execute(
            select(
                func.date(RequestLog.created_at),
                func.count(RequestLog.id),
                func.count(func.distinct(RequestLog.user_id)),
            )
            .where(RequestLog.created_at >= utcnow() - timedelta(days=days))
            .group_by(func.date(RequestLog.created_at))
        )
    ).all()
    agg = {r[0]: (r[1], r[2]) for r in rows}
    return {
        "dates": [label for _, label in date_range],
        "message_counts": [agg.get(str(d), (0, 0))[0] for d, _ in date_range],
        "active_users": [agg.get(str(d), (0, 0))[1] for d, _ in date_range],
    }


async def token_usage(db: AsyncSession, days: int = 14) -> dict:
    """按模型 × 按天 token 分布（堆叠图）。"""
    date_range = _last_days(days)
    rows = list(
        (
            await db.execute(
                select(
                    func.date(RequestLog.created_at),
                    RequestLog.model,
                    func.sum(RequestLog.total_tokens),
                )
                .where(RequestLog.created_at >= utcnow() - timedelta(days=days))
                .group_by(func.date(RequestLog.created_at), RequestLog.model)
            )
        ).all()
    )
    models = sorted({r[1] for r in rows if r[1]})
    by_date_model = {(str(r[0]), r[1]): int(r[2] or 0) for r in rows}
    series = []
    for model in models:
        series.append([by_date_model.get((str(d), model), 0) for d, _ in date_range])
    return {"dates": [label for _, label in date_range], "models": models, "series": series}


async def latency(db: AsyncSession) -> dict:
    """按天 p50/p95 延迟。"""
    days = 14
    date_range = _last_days(days)
    rows = list(
        (
            await db.execute(
                select(func.date(RequestLog.created_at), RequestLog.latency_ms)
                .where(
                    RequestLog.created_at >= utcnow() - timedelta(days=days),
                    RequestLog.latency_ms.isnot(None),
                )
            )
        ).all()
    )
    by_date: dict = {}
    for d, ms in rows:
        by_date.setdefault(str(d), []).append(ms)
    return {
        "dates": [label for _, label in date_range],
        "p50": [int(_percentile(sorted(by_date.get(str(d), [])), 0.5) or 0) for d, _ in date_range],
        "p95": [int(_percentile(sorted(by_date.get(str(d), [])), 0.95) or 0) for d, _ in date_range],
    }


async def cache(db: AsyncSession, days: int = 14) -> dict:
    """按天缓存命中率。"""
    date_range = _last_days(days)
    hits_rows = (
        await db.execute(
            select(func.date(RequestLog.created_at), func.count(RequestLog.id))
            .where(
                RequestLog.created_at >= utcnow() - timedelta(days=days),
                RequestLog.from_cache.is_(True),
            )
            .group_by(func.date(RequestLog.created_at))
        )
    ).all()
    all_rows = (
        await db.execute(
            select(func.date(RequestLog.created_at), func.count(RequestLog.id))
            .where(RequestLog.created_at >= utcnow() - timedelta(days=days))
            .group_by(func.date(RequestLog.created_at))
        )
    ).all()
    hits_map = {r[0]: r[1] for r in hits_rows}
    all_map = {r[0]: r[1] for r in all_rows}
    rates = []
    for d, _ in date_range:
        hits = hits_map.get(str(d), 0)
        total = all_map.get(str(d), 0)
        rates.append(round(hits / total * 100, 1) if total else 0)
    return {"dates": [label for _, label in date_range], "hit_rate": rates}


async def top_users(db: AsyncSession, limit: int = 10) -> list[dict]:
    rows = list(
        (
            await db.execute(
                select(
                    User.username,
                    func.count(RequestLog.id),
                    func.coalesce(func.sum(RequestLog.total_tokens), 0),
                )
                .join(User, User.id == RequestLog.user_id)
                .group_by(User.id)
                .order_by(func.count(RequestLog.id).desc())
                .limit(limit)
            )
        ).all()
    )
    return [
        {"username": r[0], "message_count": r[1], "total_tokens": int(r[2])} for r in rows
    ]
