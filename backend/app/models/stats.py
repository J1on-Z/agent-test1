"""统计与缓存模型：性能指标来源 + 语义缓存。"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.common import utcnow


class RequestLog(Base):
    """每次问答请求的性能与用量日志：支撑统计仪表盘与 p50/p95 延迟指标。"""

    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    endpoint: Mapped[str] = mapped_column(String(100))  # chat / rewrite / rerank / embedding
    model: Mapped[str | None] = mapped_column(String(50), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ttft_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    from_cache: Mapped[bool] = mapped_column(Boolean, default=False)
    # 分节点耗时分解 {rewrite: 320, retrieve: 120, rerank: 80, generate: 1500}
    node_latencies: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class SemanticCacheEntry(Base):
    """语义缓存条目：query 向量 + 记忆 hash 作为键，答案与引文整体缓存。"""

    __tablename__ = "semantic_cache_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    query_text: Mapped[str] = mapped_column(Text)
    query_embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 1024 维
    memory_hash: Mapped[str] = mapped_column(String(64), index=True)  # 历史摘要 hash（多轮隔离）
    answer: Mapped[str] = mapped_column(Text)
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
