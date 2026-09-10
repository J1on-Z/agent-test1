"""LangGraph 条件边路由函数。"""
from app.config import settings


def route_after_start(state: dict) -> str:
    """有历史且开关打开 → query 改写；否则直连检索。"""
    if settings.query_rewrite_enabled and (state.get("history_messages") or []):
        return "rewrite_query"
    return "retrieve"


def route_after_retrieve(state: dict) -> str:
    """有候选且 rerank 开启 → 精排；否则直接过门槛。"""
    if settings.rerank_enabled and (state.get("candidate_chunks") or []):
        return "rerank"
    return "context_gate"


def route_after_gate(state: dict) -> str:
    if state.get("no_context"):
        return "no_context_answer"
    return "generate"


def route_after_generate(state: dict) -> str:
    """有会话上下文时触发滚动摘要维护（内部判断阈值）。"""
    if state.get("conversation_id"):
        return "update_summary"
    return "end"
