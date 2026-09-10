"""混合检索：向量 + BM25 双路召回，RRF 融合。

RRF（Reciprocal Rank Fusion）：score(chunk) = Σ 1/(k + rank_i)，k 取 60（学界常用值）。
只依赖排名而非原始分数，天然兼容余弦相似度与 BM25 两套分数体系。
同一 chunk 双路都命中时分数累加（互惠提升）。
"""
import asyncio

from app.config import settings
from app.services.retrieval import vector_store
from app.services.retrieval.bm25 import get_bm25_index


def _rrf_fuse(
    vector_hits: list[tuple[dict, float]], bm25_hits: list[tuple[dict, float]]
) -> tuple[list[dict], dict[str, float]]:
    """按排名做 RRF 融合并去重，返回 (融合列表, chunk_id→rrf分数)。"""
    scores: dict[str, float] = {}
    chunk_map: dict[str, dict] = {}

    for rank, (item, _sim) in enumerate(vector_hits, start=1):
        cid = item["chunk_id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (settings.rrf_k + rank)
        chunk_map.setdefault(cid, item)

    for rank, (item, _score) in enumerate(bm25_hits, start=1):
        cid = item["chunk_id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (settings.rrf_k + rank)
        chunk_map.setdefault(cid, item)

    fused = [
        {**chunk_map[cid], "score": scores[cid]}
        for cid, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    ]
    return fused, scores


async def hybrid_retrieve(
    query: str, candidate_k: int | None = None, query_embedding: list[float] | None = None
) -> tuple[list[dict], dict]:
    """混合检索入口（async，供 LangGraph 节点与 debug 端点共用）。

    :param query_embedding: 预计算的查询向量（chat_service 传入，复用缓存查询的向量）
    :return: (融合候选列表, 明细 detail)
      detail = {
        "vector": [(chunk, 余弦相似度), ...],
        "bm25": [(chunk, 归一化BM25分), ...],
        "rrf_scores": {chunk_id: rrf分},
        "latency_ms": {vector: int, bm25: int, fuse: int},
      }
    """
    import time

    candidate_k = candidate_k or settings.candidate_k
    t0 = time.perf_counter()

    # 双路召回（向量检索含 embedding 网络调用，放线程池避免阻塞事件循环）
    vector_hits = await asyncio.to_thread(
        vector_store.similarity_search_with_scores, query, settings.vector_search_k, query_embedding
    )
    t1 = time.perf_counter()
    bm25 = await get_bm25_index()
    bm25_hits = bm25.search(query, settings.bm25_search_k)
    t2 = time.perf_counter()

    fused, rrf_scores = _rrf_fuse(vector_hits, bm25_hits)
    t3 = time.perf_counter()

    detail = {
        "vector": vector_hits,
        "bm25": bm25_hits,
        "rrf_scores": rrf_scores,
        "latency_ms": {
            "vector": int((t1 - t0) * 1000),
            "bm25": int((t2 - t1) * 1000),
            "fuse": int((t3 - t2) * 1000),
        },
    }
    return fused[:candidate_k], detail
