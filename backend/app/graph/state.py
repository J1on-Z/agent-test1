"""LangGraph 流水线状态定义。"""
from typing import TypedDict


class QAGraphState(TypedDict, total=False):
    # ---- 输入（由 chat_service 从 SQLite 组装） ----
    user_id: int
    conversation_id: int
    question: str                      # 原始用户问题
    history_messages: list             # 窗口内最近消息 [(role, content)]
    summary: str                       # 窗口外更早历史的滚动摘要
    model: str                         # 生成模型名
    thinking: bool                     # 思考模式开关

    # ---- 中间产物 ----
    query_embedding: list | None       # 预计算的查询向量（未被改写时检索节点直接复用）
    rewritten_query: str | None        # 多轮指代消解后的查询
    candidate_chunks: list             # RRF 融合候选 [{chunk_id, content, meta, score}]
    reranked_chunks: list              # rerank 后按分降序
    top_chunks: list                  # 进入上下文的最终 K 块（编号 1..K）
    no_context: bool                   # 相关度门槛未过
    retrieval_detail: dict             # 检索明细（debug 与统计用）

    # ---- 输出 ----
    answer: str                        # 最终回答（含【n】标注）
    usage: dict                        # token 统计
    node_latencies: dict               # 分节点耗时（写入 request_logs）
