"""检索质量评估：用金标测试集（sample_docs/golden_qa.json）评估 recall@5 与拒答率。

指标：
- recall@5：金标文档（expected_doc）的 chunk 是否进入混合检索 top5
- top1 准确率：rerank 后 top1 是否来自金标文档
- 拒答率：expected_doc 为 null 的问题被相关度门槛正确拦截的比例

用法：python scripts/eval_retrieval.py [golden_qa.json]
"""
import asyncio
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.services.retrieval import vector_store  # noqa: E402
from app.services.retrieval.bm25 import get_bm25_index  # noqa: E402
from app.services.retrieval.hybrid import hybrid_retrieve  # noqa: E402
from app.services.retrieval.reranker import rerank_candidates  # noqa: E402
from app.config import settings  # noqa: E402


def _doc_of(item: dict) -> str:
    return (item.get("meta") or {}).get("doc_name", "")


async def main() -> None:
    golden_path = Path(sys.argv[1]) if len(sys.argv) > 1 else settings.resolve_path("data/sample_docs/golden_qa.json")
    cases = json.loads(golden_path.read_text(encoding="utf-8"))
    print(f"金标测试集：{len(cases)} 题")

    await vector_store.load_index()
    await get_bm25_index()

    total, recall_hits, top1_hits, refusal_correct, refusal_total = 0, 0, 0, 0, 0
    detail_rows = []

    for case in cases:
        q = case["question"]
        expected = case.get("expected_doc")
        fused, _ = await hybrid_retrieve(q)
        reranked = await asyncio.to_thread(rerank_candidates, q, fused, settings.rerank_top_n) if fused else []

        if expected:
            total += 1
            top5_docs = {_doc_of(c) for c in fused[:5]}
            if any(expected in d for d in top5_docs):
                recall_hits += 1
            if reranked and expected in _doc_of(reranked[0]):
                top1_hits += 1
        else:
            # 无关问题：top1 rerank 分数应低于门槛（被拒答）
            refusal_total += 1
            top_score = reranked[0]["score"] if reranked else 0.0
            if top_score < settings.rerank_score_threshold:
                refusal_correct += 1
        detail_rows.append({
            "question": q[:30],
            "expected": expected,
            "top1_doc": _doc_of(reranked[0]) if reranked else "-",
            "top1_score": round(reranked[0]["score"], 3) if reranked else 0,
            "recall_hit": expected and any(expected in _doc_of(c) for c in fused[:5]),
        })

    recall = recall_hits / total if total else 0
    top1 = top1_hits / total if total else 0
    refusal = refusal_correct / refusal_total if refusal_total else 0
    print(f"\n===== 评估结果 =====")
    print(f"recall@5（混合检索）: {recall_hits}/{total} = {recall:.3f}")
    print(f"rerank top1 准确率    : {top1_hits}/{total} = {top1:.3f}")
    print(f"拒答正确率            : {refusal_correct}/{refusal_total} = {refusal:.3f}")
    print(f"\n----- 明细（未命中项） -----")
    for r in detail_rows:
        if r["expected"] and not r["recall_hit"]:
            print(f"  未命中: {r['question']} → top1={r['top1_doc']} ({r['top1_score']})")


if __name__ == "__main__":
    asyncio.run(main())
