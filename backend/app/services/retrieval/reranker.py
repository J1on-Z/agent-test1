"""重排序：DashScope qwen3.7-text-rerank（原生协议）。

端点：{dashscope_native_base_url}{rerank_path}
请求体（input 包装格式，工作空间网关硬性要求）：
  {"model": ..., "input": {"query", "documents": [...]}, "parameters": {"top_n", "return_documents"}}
响应：output.results[{index, relevance_score}]，按相关度降序（0.0-1.0，不可跨请求比较）。
"""
import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)


@retry(
    stop=stop_after_attempt(settings.llm_max_retries),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
def rerank_documents(query: str, documents: list[str], top_n: int | None = None) -> list[dict]:
    """对候选文档重排序。

    :return: [{index, score}]，按 score 降序（index 为入参 documents 中的原始位置）
    """
    with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
        resp = client.post(
            f"{settings.dashscope_native_base_url}{settings.rerank_path}",
            headers={"Authorization": f"Bearer {settings.dashscope_api_key}"},
            json={
                "model": settings.rerank_model,
                "input": {"query": query, "documents": documents},
                "parameters": {
                    "return_documents": False,
                    "top_n": top_n or settings.rerank_top_n,
                },
            },
        )
    resp.raise_for_status()
    data = resp.json()
    if "output" not in data or "results" not in data["output"]:
        logger.warning("rerank 响应格式异常: %s", str(data)[:200])
        return []
    return [
        {"index": r["index"], "score": r["relevance_score"]}
        for r in data["output"]["results"]
    ]


def rerank_candidates(query: str, candidates: list[dict], top_n: int | None = None) -> list[dict]:
    """对候选 chunk 列表重排序（业务层封装）。

    :param candidates: [{chunk_id, content, meta, score}]（混合检索融合结果）
    :return: 按 rerank 分数降序的新列表，每项带新 score
    """
    if not candidates:
        return []
    results = rerank_documents(query, [c["content"] for c in candidates], top_n=top_n)
    out = []
    for r in results:
        idx = r["index"]
        if 0 <= idx < len(candidates):
            out.append({**candidates[idx], "score": r["score"]})
    return out
