"""BM25 关键词检索：jieba 分词 + rank_bm25，索引常驻内存。

SQLite chunks 为权威数据源：服务启动与文档变更后从库中重建索引。
jieba 首次加载词典较慢（~1s），后续切词为毫秒级。
生产环境替换方案：Elasticsearch BM25（海量文档倒排/分布式召回）。
"""
import logging
import threading
from dataclasses import dataclass, field

import jieba
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)


@dataclass
class _BM25Chunk:
    chunk_id: str
    content: str
    meta: dict
    tokens: list[str] = field(repr=False)


class BM25Index:
    def __init__(self):
        self._lock = threading.Lock()
        self._chunks: list[_BM25Chunk] = []
        self._bm25: BM25Okapi | None = None

    def build(self, chunk_rows: list[dict]) -> None:
        """用 [{id, content, meta}, ...] 重建索引（在摄入 worker 线程调用）。"""
        with self._lock:
            corpus = []
            items = []
            for row in chunk_rows:
                tokens = _tokenize(row["content"])
                if not tokens:
                    continue
                corpus.append(tokens)
                items.append(
                    _BM25Chunk(
                        chunk_id=row["id"],
                        content=row["content"],
                        meta=row.get("meta") or {},
                        tokens=tokens,
                    )
                )
            self._chunks = items
            self._bm25 = BM25Okapi(corpus) if corpus else None
            logger.info("BM25 索引重建完成：%d 条 chunk", len(items))

    def search(self, query: str, k: int) -> list[tuple[dict, float]]:
        """返回 [(chunk 信息, 归一化分数)]。分数归一化到 [0,1]，实际融合只取排名（RRF）。"""
        with self._lock:
            if self._bm25 is None:
                return []
            tokens = _tokenize(query)
            scores = self._bm25.get_scores(tokens)
            if not scores.any():
                return []
            top_idx = scores.argsort()[::-1][:k]
            max_score = float(scores.max())
            out = []
            for i in top_idx:
                raw = float(scores[i])
                if raw <= 0:
                    continue
                item = self._chunks[i]
                out.append(
                    (
                        {"chunk_id": item.chunk_id, "content": item.content, "meta": item.meta},
                        raw / max_score if max_score > 0 else 0.0,
                    )
                )
            return out

    @property
    def size(self) -> int:
        return len(self._chunks)


_instance = BM25Index()


def _tokenize(text: str) -> list[str]:
    """jieba 精确模式分词，过滤空白 token。"""
    return [t.strip() for t in jieba.lcut(text) if t.strip()]


async def get_bm25_index() -> BM25Index:
    """获取索引；为空时从 SQLite chunks 全量重建（服务启动调用）。"""
    if _instance.size > 0:
        return _instance
    from app.services.kb_service import load_all_chunks_sync

    await load_all_chunks_sync()  # 该函数负责调 _instance.build
    return _instance


def rebuild_from_rows_sync(rows: list[dict]) -> None:
    _instance.build(rows)
