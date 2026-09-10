"""LangGraph 流水线组装。

设计说明：
- 无 checkpointer：每次请求独立建图执行，多轮上下文由 chat_service 从 SQLite
  组装进初始 State —— 与「不同时间登录找回历史对话」的持久化需求一致；
  生产环境可换 Postgres Checkpointer + LangGraph Platform（README 对照说明）。
- 服务依赖经 nodes.init_services 注入，节点保持纯函数，便于单测注入 Fake 模型。
"""
from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.graph import edges, nodes
from app.graph.state import QAGraphState

_graph = None  # 每次调用 run 使用同一编译图（compile 是纯组装，无状态）


def build_qa_graph() -> "StateGraph":
    global _graph
    if _graph is not None:
        return _graph

    g = StateGraph(QAGraphState)
    g.add_node("rewrite_query", nodes.rewrite_query)
    g.add_node("retrieve", nodes.retrieve)
    g.add_node("rerank", nodes.rerank)
    g.add_node("context_gate", nodes.context_gate)
    g.add_node("generate", nodes.generate)
    g.add_node("no_context_answer", nodes.no_context_answer)
    g.add_node("update_summary", nodes.update_summary)

    g.add_conditional_edges(START, edges.route_after_start, {
        "rewrite_query": "rewrite_query",
        "retrieve": "retrieve",
    })
    g.add_edge("rewrite_query", "retrieve")
    g.add_conditional_edges("retrieve", edges.route_after_retrieve, {
        "rerank": "rerank",
        "context_gate": "context_gate",
    })
    g.add_edge("rerank", "context_gate")
    g.add_conditional_edges("context_gate", edges.route_after_gate, {
        "generate": "generate",
        "no_context_answer": "no_context_answer",
    })
    g.add_conditional_edges("generate", edges.route_after_generate, {
        "update_summary": "update_summary",
        "end": END,
    })
    g.add_edge("no_context_answer", END)
    g.add_edge("update_summary", END)

    _graph = g.compile()
    return _graph
