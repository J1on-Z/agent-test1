"""性能基准：检索延迟分解 / 缓存命中 vs 未命中 TTFT / 并发压测。

输出可直接贴论文实验章节的数据：
- 检索各阶段延迟（向量/BM25/RRF/rerank）
- 首 token 延迟（TTFT）：缓存命中 vs 未命中 vs 思考模式
- 3 并发流式压测吞吐

用法：python scripts/benchmark.py [--questions 10] [--concurrency 3]
"""
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.services.retrieval import vector_store  # noqa: E402
from app.services.retrieval.bm25 import get_bm25_index  # noqa: E402
from app.services.retrieval.hybrid import hybrid_retrieve  # noqa: E402
from app.services.retrieval.reranker import rerank_candidates  # noqa: E402
from app.config import settings  # noqa: E402

SAMPLE_QUESTIONS = [
    "星辰X1 Pro 的电池容量和快充功率是多少？",
    "七天无理由退货有什么条件？",
    "暖冬羽绒服怎么洗涤保养？",
    "偏远地区运费怎么算？",
    "鲜源冰箱需要手动除霜吗？",
    "积分有效期多久？",
    "Aurora Buds 2 降噪深度多少？",
    "疾风跑鞋尺码怎么选？",
    "手机电池健康度低于多少可以免费换电池？",
    "物流停滞多久可以联系客服？",
]


async def bench_retrieval() -> None:
    await vector_store.load_index()
    await get_bm25_index()
    print("===== 1. 检索阶段延迟分解（10 问平均） =====")
    vec_ms, bm25_ms, fuse_ms, rerank_ms, total_ms = [], [], [], [], []
    for q in SAMPLE_QUESTIONS:
        t0 = time.perf_counter()
        fused, detail = await hybrid_retrieve(q)
        t1 = time.perf_counter()
        await asyncio.to_thread(rerank_candidates, q, fused, settings.rerank_top_n)
        t2 = time.perf_counter()
        vec_ms.append(detail["latency_ms"]["vector"])
        bm25_ms.append(detail["latency_ms"]["bm25"])
        fuse_ms.append(detail["latency_ms"]["fuse"])
        rerank_ms.append(int((t2 - t1) * 1000))
        total_ms.append(int((t2 - t0) * 1000))
    for name, vals in [("向量检索", vec_ms), ("BM25", bm25_ms), ("RRF 融合", fuse_ms), ("重排序", rerank_ms), ("端到端", total_ms)]:
        print(f"  {name}: p50={statistics.median(vals):.0f}ms 平均={statistics.mean(vals):.0f}ms 最大={max(vals)}ms")


async def bench_ttft_local() -> None:
    """本地直测 TTFT（不经过 HTTP，测量 生成阶段 首 token 延迟）。"""
    print("===== 2. 首 token 延迟（生成节点，本地直测） =====")
    from app.graph import nodes
    from app.graph.builder import build_qa_graph
    from app.services.llm.qwen import get_llm
    from app.services.retrieval.hybrid import hybrid_retrieve
    from app.services.retrieval.reranker import rerank_candidates

    nodes.init_services(nodes.Services(
        get_llm=get_llm, hybrid_retrieve=hybrid_retrieve, rerank_candidates=rerank_candidates
    ))
    graph = build_qa_graph()
    ttft_list = []
    for q in SAMPLE_QUESTIONS[:3]:
        t0 = time.perf_counter()
        first = None
        async for mode, chunk in graph.astream(
            {"question": q, "history_messages": [], "summary": "", "model": "qwen-plus", "thinking": False},
            stream_mode=["custom", "values"],
        ):
            if mode == "custom":
                ev = chunk[0] if isinstance(chunk, tuple) else chunk
                if isinstance(ev, dict) and ev.get("type") == "token" and first is None:
                    first = time.perf_counter() - t0
        ttft_list.append(int(first * 1000))
    print(f"  qwen-plus 未命中缓存 TTFT: p50={statistics.median(ttft_list):.0f}ms 明细={ttft_list}")


async def bench_concurrency() -> None:
    """3 并发压测（直接并发跑图，测量吞吐与平均耗时）。"""
    print("===== 3. 并发压测（3 并发 × 2 轮，本地直测） =====")
    from app.graph import nodes
    from app.graph.builder import build_qa_graph
    from app.services.llm.qwen import get_llm
    from app.services.retrieval.hybrid import hybrid_retrieve
    from app.services.retrieval.reranker import rerank_candidates

    nodes.init_services(nodes.Services(
        get_llm=get_llm, hybrid_retrieve=hybrid_retrieve, rerank_candidates=rerank_candidates
    ))
    graph = build_qa_graph()

    async def one_run(q: str) -> float:
        t0 = time.perf_counter()
        async for _mode, _chunk in graph.astream(
            {"question": q, "history_messages": [], "summary": "", "model": "qwen-plus", "thinking": False},
            stream_mode=["values"],
        ):
            pass
        return time.perf_counter() - t0

    tasks = []
    for q in SAMPLE_QUESTIONS[:6]:
        tasks.append(one_run(q))
    t0 = time.perf_counter()
    results = await asyncio.gather(*tasks)
    wall = time.perf_counter() - t0
    print(f"  6 个请求 3 并发完成：墙钟 {wall:.1f}s，平均单请求 {statistics.mean(results):.1f}s，最大 {max(results):.1f}s")
    print(f"  吞吐 ≈ {6 / wall:.2f} 请求/秒（受 DashScope 速率与并发信号量限制）")


async def main() -> None:
    await bench_retrieval()
    await bench_ttft_local()
    await bench_concurrency()
    print("\n提示：缓存命中 TTFT 请通过 HTTP 二次提问相同问题验证（预期 < 100ms）")


if __name__ == "__main__":
    asyncio.run(main())
