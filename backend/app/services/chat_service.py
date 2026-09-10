"""聊天编排核心：组装状态 → LangGraph 流式执行 → 引文解析 → 持久化 → SSE 事件。

SSE 事件序列（与前端约定）：
  meta(会话/消息/模型) → token*(逐字) → [thinking*] → citations → done(usage/延迟/缓存)
  异常时 error；客户端断开时已生成部分以 interrupted 状态落库。
"""
import asyncio
import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import BizError
from app.database import AsyncSessionLocal
from app.graph import nodes
from app.graph.builder import build_qa_graph
from app.models import (
    MSG_INTERRUPTED,
    MSG_NORMAL,
    ROLE_ASSISTANT,
    ROLE_USER,
    Chunk,
    Conversation,
    Message,
    RequestLog,
    User,
)
from app.models.common import utcnow
from app.schemas.chat import ChatRequest
from app.services import memory_service
from app.services.llm.qwen import get_llm, resolve_model
from app.services.retrieval.hybrid import hybrid_retrieve
from app.services.retrieval.reranker import rerank_candidates
from app.utils import sse
from app.utils.text import parse_citation_indexes, truncate_title

logger = logging.getLogger(__name__)

_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = build_qa_graph()
    return _graph


def _is_model_denied(err: Exception) -> bool:
    """模型未开通/额度耗尽类错误（给用户友好指引而非原始报文）。"""
    msg = str(err)
    return any(k in msg for k in ("Unpurchased", "AccessDenied", "Access to model denied"))


def _ensure_services() -> None:
    """注入图节点依赖（幂等）。"""
    nodes.init_services(
        nodes.Services(
            get_llm=get_llm,
            hybrid_retrieve=hybrid_retrieve,
            rerank_candidates=rerank_candidates,
            update_summary=memory_service.maybe_update_summary,
        )
    )




async def _save_user_message(
    db: AsyncSession, conversation: Conversation, question: str
) -> Message:
    msg = Message(conversation_id=conversation.id, role=ROLE_USER, content=question)
    db.add(msg)
    if conversation.message_count == 0:
        conversation.title = truncate_title(question)
    conversation.message_count += 1
    conversation.updated_at = utcnow()
    await db.commit()
    await db.refresh(msg)
    return msg


async def _persist_assistant_message(
    db: AsyncSession,
    conversation: Conversation,
    answer: str,
    citations: list,
    model: str,
    usage: dict,
    latency_ms: int,
    ttft_ms: int | None,
    from_cache: bool,
    status: str = MSG_NORMAL,
) -> Message:
    msg = Message(
        conversation_id=conversation.id,
        role=ROLE_ASSISTANT,
        content=answer,
        model=model,
        citations=citations,
        token_usage=usage or None,
        latency_ms=latency_ms,
        ttft_ms=ttft_ms,
        from_cache=from_cache,
        status=status,
    )
    db.add(msg)
    conversation.message_count += 1
    conversation.updated_at = utcnow()
    await db.commit()
    await db.refresh(msg)
    return msg


async def _write_request_log(
    db: AsyncSession,
    user: User,
    conversation_id: int,
    message_id: int,
    model: str,
    usage: dict,
    latency_ms: int,
    ttft_ms: int | None,
    from_cache: bool,
    node_latencies: dict | None,
) -> None:
    db.add(
        RequestLog(
            user_id=user.id,
            conversation_id=conversation_id,
            message_id=message_id,
            endpoint="chat",
            model=model,
            prompt_tokens=usage.get("input_tokens", usage.get("prompt_tokens", 0)) if usage else 0,
            completion_tokens=usage.get("output_tokens", usage.get("completion_tokens", 0)) if usage else 0,
            total_tokens=usage.get("total_tokens", 0) if usage else 0,
            latency_ms=latency_ms,
            ttft_ms=ttft_ms,
            from_cache=from_cache,
            node_latencies=node_latencies,
        )
    )
    await db.commit()


async def _map_citations(
    db: AsyncSession, answer: str, top_chunks: list[dict]
) -> list[dict]:
    """回答中的【n】编号 → 结构化引文列表（引文块与消息一起持久化，历史会话可直接还原）。"""
    indexes = parse_citation_indexes(answer, len(top_chunks))
    if not indexes:
        return []
    chunk_ids = [top_chunks[i - 1]["chunk_id"] for i in indexes]
    rows = list((await db.scalars(select(Chunk).where(Chunk.id.in_(chunk_ids)))).all())
    row_map = {c.id: c for c in rows}
    citations = []
    for i in indexes:
        chunk_info = top_chunks[i - 1]
        chunk = row_map.get(chunk_info["chunk_id"])
        meta = chunk_info.get("meta") or {}
        citations.append(
            {
                "index": i,
                "chunk_id": chunk_info["chunk_id"],
                "doc_id": chunk.document_id if chunk else None,
                "doc_name": meta.get("doc_name", "未知文档"),
                "title": meta.get("doc_title") or meta.get("title") or "",
                "page": meta.get("page"),
                "snippet": (chunk_info.get("content") or "")[:200],
                "score": round(float(chunk_info.get("score", 0.0)), 4),
            }
        )
    return citations


async def _get_owned_conversation_or_create(
    db: AsyncSession, user: User, conversation_id: int | None
) -> Conversation:
    if conversation_id is None:
        conversation = Conversation(user_id=user.id, title="新会话", message_count=0)
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)
        return conversation
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise BizError("not_found", "会话不存在", 404)
    return conversation


async def stream_chat(
    user: User, body: ChatRequest, db: AsyncSession
):
    """SSE 流式问答生成器。"""
    _ensure_services()
    t_start = time.perf_counter()
    model = resolve_model(body.model)
    conversation = await _get_owned_conversation_or_create(db, user, body.conversation_id)
    user_msg = await _save_user_message(db, conversation, body.question)
    window, summary = await memory_service.get_memory_context(
        db, conversation.id, exclude_message_id=user_msg.id
    )

    # 缓存两级查找：精确匹配（无需向量，毫秒级）→ 语义匹配（换措辞的相似问题）
    from app.services import cache_service
    from app.services.llm.embeddings import get_embeddings
    from app.utils.hashing import sha256_text

    memory_hash = (
        sha256_text(summary) if settings.semantic_cache_memory_aware else "global"
    )
    cache_hit = (
        await cache_service.lookup_exact(db, body.question, memory_hash)
        if settings.semantic_cache_enabled else None
    )
    query_embedding = None
    if cache_hit is None:
        # 查询向量：语义缓存查找与向量检索共用（省一次 embedding 网络调用）
        query_embedding = await asyncio.to_thread(get_embeddings().embed_query, body.question)
        if settings.semantic_cache_enabled:
            cache_hit = await cache_service.lookup(db, query_embedding, memory_hash)

    yield sse.sse_meta(
        conversation_id=conversation.id,
        user_message_id=user_msg.id,
        model=model,
        thinking=body.thinking,
    )

    if cache_hit is not None:
        # 缓存命中：直接回放完整回答（零 LLM 调用）
        answer = cache_hit["answer"]
        citations = cache_hit["citations"]
        yield sse.sse_token(answer)
        yield sse.sse_citations(citations)
        assistant_msg = await _persist_assistant_message(
            db, conversation, answer, citations, model, {}, 0, 0, True
        )
        # 缓存命中同样计入 request_logs（from_cache=True），支撑按天命中率统计
        await _write_request_log(
            db, user, conversation.id, assistant_msg.id, model, {},
            0, 0, True, None,
        )
        yield sse.sse_done(
            message_id=assistant_msg.id,
            usage={},
            latency_ms=0,
            ttft_ms=0,
            from_cache=True,
        )
        return

    state = {
        "user_id": user.id,
        "conversation_id": conversation.id,
        "question": body.question,
        "query_embedding": query_embedding,
        "history_messages": window,
        "summary": summary,
        "model": model,
        "thinking": body.thinking,
    }

    answer = ""
    ttft_ms = None
    final_state = None
    usage = {}
    node_latencies = {}
    try:
        async for mode, chunk in _get_graph().astream(state, stream_mode=["custom", "values"]):
            if mode == "custom":
                event = chunk[0] if isinstance(chunk, tuple) else chunk
                if not isinstance(event, dict):
                    continue
                if event.get("type") == "token" and event.get("delta"):
                    if ttft_ms is None:
                        ttft_ms = int((time.perf_counter() - t_start) * 1000)
                    answer += event["delta"]
                    yield sse.sse_token(event["delta"])
                elif event.get("type") == "thinking" and event.get("delta"):
                    yield sse.sse_meta_thinking(event["delta"])
            else:
                final_state = chunk

        if final_state is None:
            raise RuntimeError("流水线未返回终态")
        # 拒答路径不产生 token 流：从终态取值并补发一帧，前端统一按 token 渲染
        if not answer and final_state.get("answer"):
            answer = final_state["answer"]
            yield sse.sse_token(answer)
        usage = final_state.get("usage") or {}
        node_latencies = final_state.get("node_latencies") or {}
        top_chunks = final_state.get("top_chunks") or []
        latency_ms = int((time.perf_counter() - t_start) * 1000)

        citations = await _map_citations(db, answer, top_chunks)
        assistant_msg = await _persist_assistant_message(
            db, conversation, answer, citations, model, usage,
            latency_ms, ttft_ms, False,
        )
        await _write_request_log(
            db, user, conversation.id, assistant_msg.id, model, usage,
            latency_ms, ttft_ms, False, node_latencies,
        )
        # 写入语义缓存（拒答为确定性文案，不入缓存；下次相同/相似问题直接命中）
        if settings.semantic_cache_enabled and answer and not final_state.get("no_context"):
            await cache_service.store(db, body.question, query_embedding, memory_hash, answer, citations)
        yield sse.sse_citations(citations)
        yield sse.sse_done(
            message_id=assistant_msg.id,
            usage=usage,
            latency_ms=latency_ms,
            ttft_ms=ttft_ms,
            from_cache=False,
        )
    except asyncio.CancelledError:
        # 客户端断开：已生成部分以 interrupted 状态落库
        asyncio.get_running_loop().create_task(
            _persist_partial_interrupted(conversation.id, answer, model)
        )
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("流式问答异常")
        if answer:
            asyncio.get_running_loop().create_task(
                _persist_partial_interrupted(conversation.id, answer, model)
            )
        if _is_model_denied(e):
            yield sse.sse_error(
                "model_unavailable",
                "模型服务暂不可用：请到阿里云百炼控制台「模型广场」开通对话模型"
                "（如 qwen-plus / qwen-max），或检查账号余额与免费额度状态。",
            )
        else:
            yield sse.sse_error("chat_error", f"回答生成失败：{e}")


async def _persist_partial_interrupted(
    conversation_id: int, answer: str, model: str
) -> None:
    """断连/异常时持久化已生成的部分回答。"""
    try:
        async with AsyncSessionLocal() as db:
            conversation = await db.get(Conversation, conversation_id)
            if conversation is None or not answer:
                return
            db.add(
                Message(
                    conversation_id=conversation_id,
                    role=ROLE_ASSISTANT,
                    content=answer,
                    model=model,
                    citations=[],
                    status=MSG_INTERRUPTED,
                )
            )
            conversation.message_count += 1
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("中断消息持久化失败")


async def regenerate(user: User, message_id: int, db: AsyncSession):
    """重新生成：删除该 assistant 消息及其后所有消息，以同一问题重新生成。"""
    msg = await db.get(Message, message_id)
    if msg is None or msg.role != ROLE_ASSISTANT:
        raise BizError("bad_message", "只能对助手消息执行重新生成", 404)
    conversation = await db.get(Conversation, msg.conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise BizError("not_found", "会话不存在", 404)
    user_msg = await db.scalar(
        select(Message)
        .where(Message.conversation_id == conversation.id, Message.role == ROLE_USER, Message.id < msg.id)
        .order_by(Message.id.desc())
    )
    if user_msg is None:
        raise BizError("bad_message", "找不到对应的用户问题", 404)

    # 删除 assistant 及其后所有消息
    later = list(
        (
            await db.scalars(
                select(Message).where(
                    Message.conversation_id == conversation.id, Message.id >= msg.id
                )
            )
        ).all()
    )
    for m in later:
        await db.delete(m)
    conversation.message_count = max(0, conversation.message_count - len(later))
    await db.commit()

    body = ChatRequest(conversation_id=conversation.id, question=user_msg.content)
    async for frame in stream_chat(user, body, db):
        yield frame


async def mark_interrupted(user: User, message_id: int, db: AsyncSession) -> None:
    """停止生成兜底：把消息标记为 interrupted（客户端断开为主路径）。"""
    msg = await db.get(Message, message_id)
    if msg is None or msg.role != ROLE_ASSISTANT:
        raise BizError("bad_message", "消息不存在", 404)
    conversation = await db.get(Conversation, msg.conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise BizError("not_found", "会话不存在", 404)
    msg.status = MSG_INTERRUPTED
    await db.commit()
