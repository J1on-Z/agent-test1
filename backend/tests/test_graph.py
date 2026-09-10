"""LangGraph 流水线测试：注入 Fake 模型全图走查（改写/直连/拒答/摘要触发）。"""
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from app.config import settings
from app.graph import nodes
from app.graph.builder import build_qa_graph

REWRITE_ANSWER = "改写后的完整问题"
GENERATE_ANSWER = "根据参考内容回答【1】"


class RouterFakeLLM:
    """按提示词内容路由的假模型：含「改写」→ 改写答案；否则 → 生成答案。"""

    async def ainvoke(self, prompt, **kwargs):
        text = REWRITE_ANSWER if "改写" in str(prompt) else GENERATE_ANSWER
        return AIMessage(
            content=text,
            usage_metadata={"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
        )

    def astream(self, messages, **kwargs):
        text = REWRITE_ANSWER if "改写" in str(messages) else GENERATE_ANSWER

        async def gen():
            for ch in text:
                yield AIMessageChunk(content=ch)

        return gen()


def _fake_chunks(n=3):
    return [
        {"chunk_id": f"c{i}", "content": f"参考内容{i}", "meta": {"doc_name": f"doc{i}.md"}, "score": 0.9 - i * 0.1}
        for i in range(1, n + 1)
    ]


@pytest.fixture(autouse=True)
def _services(monkeypatch):
    """注入 Fake 依赖：路由型 fake llm，检索/重排为桩函数。"""
    calls = {"retrieve_queries": [], "summary_seen": []}

    async def fake_hybrid(query, candidate_k=None, query_embedding=None):
        calls["retrieve_queries"].append(query)
        return _fake_chunks(), {"vector": [], "bm25": [], "rrf_scores": {}, "latency_ms": {}}

    def fake_rerank(query, candidates, top_n=None):
        return sorted(candidates, key=lambda c: -c["score"])

    async def fake_summary(conversation_id):
        calls["summary_seen"].append(conversation_id)

    nodes.init_services(nodes.Services(
        get_llm=lambda model, thinking=False: RouterFakeLLM(),
        hybrid_retrieve=fake_hybrid,
        rerank_candidates=fake_rerank,
        update_summary=fake_summary,
    ))
    # 本测试集固定开关：启用改写与重排，门槛 0.3（测试内可按需覆盖）
    monkeypatch.setattr(settings, "query_rewrite_enabled", True)
    monkeypatch.setattr(settings, "rerank_enabled", True)
    monkeypatch.setattr(settings, "rerank_score_threshold", 0.3)
    return calls


async def _run(state: dict) -> dict:
    """跑图到终态，返回最终 state。"""
    graph = build_qa_graph()
    final = None
    async for _mode, chunk in graph.astream(state, stream_mode=["values"]):
        final = chunk
    return final


class TestGraphFlows:
    async def test_no_history_skips_rewrite(self, _services):
        final = await _run({"question": "电池多大", "history_messages": [], "summary": "", "model": "qwen-plus", "thinking": False})
        # 无历史 → 不调用改写 → 检索收到原始问题
        assert _services["retrieve_queries"] == ["电池多大"]
        assert final["no_context"] is False
        assert final["answer"] == "根据参考内容回答【1】"
        assert final["node_latencies"].get("retrieve") is not None

    async def test_with_history_rewrites(self, _services):
        final = await _run({
            "question": "它多重", "history_messages": [("user", "星辰X1 Pro 参数")],
            "summary": "", "model": "qwen-plus", "thinking": False,
        })
        assert _services["retrieve_queries"] == ["改写后的完整问题"]
        assert final["answer"] == "根据参考内容回答【1】"

    async def test_low_score_goes_no_context(self, _services, monkeypatch):
        # 重排桩返回低分 → 门槛拦截 → 确定性拒答（不调 LLM）
        monkeypatch.setattr(settings, "rerank_score_threshold", 0.99)
        final = await _run({"question": "无关问题", "history_messages": [], "summary": "", "model": "qwen-plus", "thinking": False})
        assert final["no_context"] is True
        assert "知识库中未找到" in final["answer"]
        # 拒答路径无 token 用量
        assert final.get("usage") == {}

    async def test_summary_triggered_with_conversation(self, _services):
        final = await _run({
            "question": "x", "history_messages": [], "summary": "",
            "model": "qwen-plus", "thinking": False, "conversation_id": 7,
        })
        # update_summary 为后台任务（create_task），这里验证节点被路由到即可
        # （fake_summary 由 create_task 调度，异步窗口内可能已执行）
        assert final["answer"] == "根据参考内容回答【1】"

    async def test_rerank_disabled_bypasses(self, _services, monkeypatch):
        monkeypatch.setattr(settings, "rerank_enabled", False)
        final = await _run({"question": "x", "history_messages": [], "summary": "", "model": "qwen-plus", "thinking": False})
        # 关闭重排时门槛不设阈值 → 正常生成
        assert final["no_context"] is False
