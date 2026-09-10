"""LangGraph 流水线节点实现。

节点为纯函数（依赖通过 init_services 注入，便于用 Fake 模型单测）。
流式输出约定：generate 节点通过 get_stream_writer 发射自定义事件
  {"type": "token", "delta": ...} / {"type": "thinking", "delta": ...}，
由 chat_service 以 astream(stream_mode=["custom", "values"]) 消费。
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Callable

from langgraph.config import get_stream_writer

from app.config import settings
from app.services.llm.prompts import NO_CONTEXT_ANSWER, REWRITE_PROMPT, build_messages
from app.services.llm.qwen import llm_slot

logger = logging.getLogger(__name__)


@dataclass
class Services:
    """节点依赖注入（builder 组装；测试注入 Fake）。"""

    get_llm: Callable = None          # (model, thinking) -> ChatOpenAI
    hybrid_retrieve: Callable = None  # (query, k) -> (fused, detail)
    rerank_candidates: Callable = None  # (query, candidates, top_n) -> list
    update_summary: Callable = None   # (conversation_id) -> None 后台任务


_SERVICES: Services | None = None


def init_services(services: Services) -> None:
    global _SERVICES
    _SERVICES = services


def _now_ms() -> float:
    return time.perf_counter() * 1000


def _record(state: dict, node: str, elapsed_ms: float) -> dict:
    latencies = dict(state.get("node_latencies") or {})
    latencies[node] = int(elapsed_ms)
    return latencies


# ---------------------------------------------------------------- 节点

async def rewrite_query(state: dict) -> dict:
    """多轮指代消解：把「那这款的运费呢」改写为可独立检索的完整问题。"""
    history = state.get("history_messages") or []
    question = state["question"]
    if not history or not settings.query_rewrite_enabled:
        return {"rewritten_query": None}

    t0 = _now_ms()
    llm = _SERVICES.get_llm(settings.llm_model, thinking=False)
    prompt = REWRITE_PROMPT.format(
        history="\n".join(f"{r}: {c}" for r, c in history[-4:]),
        question=question,
    )
    try:
        async with llm_slot():  # 全局并发闸门（与生成请求共用配额）
            resp = await llm.ainvoke(prompt)
        rewritten = (resp.content or "").strip() or question
    except Exception as e:  # noqa: BLE001 改写是优化步骤，失败降级为原始问题
        logger.warning("query 改写失败，降级使用原始问题: %s", str(e)[:100])
        rewritten = question
    logger.debug("query 改写: %s -> %s", question, rewritten)
    return {
        "rewritten_query": rewritten,
        "node_latencies": _record(state, "rewrite", _now_ms() - t0),
    }


async def retrieve(state: dict) -> dict:
    """混合检索：向量 + BM25 双路召回 → RRF 融合。

    query 未被改写时可复用调用方预计算的查询向量（省一次 embedding 调用）。
    """
    query = state.get("rewritten_query") or state["question"]
    query_embedding = None
    if not state.get("rewritten_query"):
        query_embedding = state.get("query_embedding")
    t0 = _now_ms()
    fused, detail = await _SERVICES.hybrid_retrieve(query, query_embedding=query_embedding)
    return {
        "candidate_chunks": fused,
        "retrieval_detail": detail,
        "node_latencies": _record(state, "retrieve", _now_ms() - t0),
    }


async def rerank(state: dict) -> dict:
    """精排：gte/qwen rerank 模型对候选重打分（同步 httpx 放线程池）。"""
    candidates = state.get("candidate_chunks") or []
    if not settings.rerank_enabled or not candidates:
        return {"reranked_chunks": candidates}
    query = state.get("rewritten_query") or state["question"]
    t0 = _now_ms()
    top_n = max(settings.rerank_top_n, settings.final_top_k)
    reranked = await asyncio.to_thread(
        _SERVICES.rerank_candidates, query, candidates, top_n
    )
    return {
        "reranked_chunks": reranked,
        "node_latencies": _record(state, "rerank", _now_ms() - t0),
    }


def context_gate(state: dict) -> dict:
    """相关度门槛：纯逻辑（非 LLM），最高分 < 阈值或为空 → 拒答。

    通过门槛后按阈值过滤低分块（避免无关块混入上下文稀释生成质量），
    再截取 final_top_k。rerank 关闭时不做过滤（RRF 分数不可比）。
    """
    # rerank 关闭时该节点被跳过，回退使用混合检索候选（此时不设分数门槛）
    candidates = state.get("reranked_chunks") or state.get("candidate_chunks") or []
    threshold = (
        settings.rerank_score_threshold if settings.rerank_enabled else 0.0
    )
    if not candidates or candidates[0].get("score", 0.0) < threshold:
        return {"no_context": True, "top_chunks": []}
    if settings.rerank_enabled:
        candidates = [c for c in candidates if c.get("score", 0.0) >= threshold]
    return {
        "no_context": False,
        "top_chunks": candidates[: settings.final_top_k],
    }


def _is_stream_denied(err: Exception) -> bool:
    """模型网关对流式未授权/未开通的典型错误（403 / Unpurchased / denied）。"""
    msg = str(err)
    return any(k in msg for k in ("403", "denied", "Denied", "Unpurchased", "AccessDenied"))


async def generate(state: dict) -> dict:
    """带引用的流式生成：编号上下文 + 硬约束引用标注。

    通过 custom stream 逐 token 推送（get_stream_writer 由 LangGraph 运行时注入）。
    容错：模型网关拒绝流式（未开通 stream 权限）时自动降级为非流式调用，
    把全文作为单帧 token 发出，前端渲染路径无感知。
    """
    t0 = _now_ms()
    llm = _SERVICES.get_llm(state["model"], state.get("thinking", False))
    messages = build_messages(
        state["question"],
        state.get("history_messages") or [],
        state.get("summary") or "",
        state["top_chunks"],
    )

    full_text = ""
    usage: dict = {}
    try:
        writer = get_stream_writer()
    except Exception:  # noqa: BLE001 非 custom 流模式（如单测）无 writer
        writer = None

    def _emit(event: dict) -> None:
        if writer:
            writer(event)

    async def _stream():
        nonlocal full_text, usage
        # 全局并发闸门：整个流式生成期间占用一个槽位，
        # 100 并发时超出 LLM_MAX_CONCURRENCY 的请求在此排队（而非被 DashScope 拒绝）
        async with llm_slot():
            async for chunk in llm.astream(messages):
                delta = chunk.content
                if isinstance(delta, str) and delta:
                    full_text += delta
                    _emit({"type": "token", "delta": delta})
                reasoning = (chunk.additional_kwargs or {}).get("reasoning_content")
                if reasoning:
                    _emit({"type": "thinking", "delta": reasoning})
                # usage 可能出现在 usage_metadata 或 response_metadata（网关行为有差异）
                if chunk.usage_metadata:
                    usage = dict(chunk.usage_metadata)
                elif (chunk.response_metadata or {}).get("token_usage"):
                    usage = dict(chunk.response_metadata["token_usage"])

    try:
        await _stream()
    except Exception as err:  # noqa: BLE001
        if not _is_stream_denied(err):
            raise
        logger.warning("流式调用被网关拒绝，降级为非流式（一次性返回）: %s", str(err)[:120])
        async with llm_slot():  # 降级分支同样受并发闸门保护
            resp = await llm.ainvoke(messages)
        full_text = resp.content or ""
        usage = dict(resp.usage_metadata or {})
        _emit({"type": "token", "delta": full_text})
        reasoning = (resp.additional_kwargs or {}).get("reasoning_content")
        if reasoning:
            _emit({"type": "thinking", "delta": reasoning})

    return {
        "answer": full_text,
        "usage": usage,
        "node_latencies": _record(state, "generate", _now_ms() - t0),
    }


async def no_context_answer(state: dict) -> dict:
    """确定性拒答（不调 LLM）：零成本、可评估拒答率。

    附带低分候选的文档名作为「您可能想问」建议。
    """
    candidates = state.get("reranked_chunks") or []
    suggestions = []
    seen = set()
    for c in candidates:
        doc = (c.get("meta") or {}).get("doc_name")
        if doc and doc not in seen:
            seen.add(doc)
            suggestions.append(doc)
    answer = NO_CONTEXT_ANSWER
    if suggestions:
        answer += "\n\n您可能想问（相关知识库文档）：" + "、".join(f"《{s}》" for s in suggestions[:3])
    return {"answer": answer, "usage": {}, "node_latencies": _record(state, "no_context", 0)}


async def update_summary(state: dict) -> dict:
    """滚动摘要维护：后台异步执行（不阻塞回答返回），memory_service 内部判断触发阈值。"""
    conversation_id = state.get("conversation_id")
    if conversation_id and _SERVICES.update_summary:
        asyncio.get_running_loop().create_task(
            _SERVICES.update_summary(conversation_id)
        )
    return {}
