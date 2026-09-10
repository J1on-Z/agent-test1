"""自研轻量向量检索：SQLite 持久化（vector_embeddings 表）+ numpy 内存矩阵。

选型背景：chromadb 1.5.9 的 chroma-hnswlib 原生扩展在 Python 3.14 / Windows
下 upsert 稳定段错误（最小复现脚本可验证），故按预案改为自研实现：
- 持久化：float32 原始字节存 SQLite（1024 维 ≈ 4KB/条）
- 检索：内存矩阵行归一化后点积求余弦相似度，万级 chunk 单次查询 <10ms
- 线程安全：所有读写持全局锁串行化
生产环境替换方案：Milvus / Qdrant（HNSW 索引、亿级向量、GPU 检索），README 有对照说明。
"""
import logging
import threading

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.database import SyncSessionLocal
from app.models import Chunk, VectorEmbedding
from app.services.llm.embeddings import get_embeddings

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()

# 内存索引：chunk_id → {vec: float32 归一化向量, content, meta}
_INDEX: dict[str, dict] = {}
_MATRIX: np.ndarray | None = None  # (N, dim) 行归一化矩阵
_IDS: list[str] = []


def _rebuild_matrix() -> None:
    global _MATRIX, _IDS
    if not _INDEX:
        _MATRIX, _IDS = None, []
        return
    ids = list(_INDEX.keys())
    mat = np.stack([_INDEX[i]["vec"] for i in ids]).astype(np.float32)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    _MATRIX, _IDS = mat / norms, ids


# ---------------------------------------------------------------- 生命周期

async def load_index() -> None:
    """服务启动时从 SQLite 全量装载向量与 chunk 内容到内存索引。"""
    import asyncio

    await asyncio.to_thread(_load_index_sync)


def _load_index_sync() -> None:
    global _INDEX
    with _LOCK:
        with SyncSessionLocal() as db:
            rows = db.execute(
                select(Chunk.id, Chunk.content, Chunk.meta, VectorEmbedding.embedding)
                .join(VectorEmbedding, VectorEmbedding.chunk_id == Chunk.id)
            ).all()
        _INDEX = {
            chunk_id: {
                "vec": np.frombuffer(emb, dtype=np.float32),
                "content": content,
                "meta": meta or {},
            }
            for chunk_id, content, meta, emb in rows
        }
        _rebuild_matrix()
        logger.info("向量索引装载完成：%d 条", len(_INDEX))


# ---------------------------------------------------------------- 写操作

def _vec_bytes(vec: list[float]) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def raw_upsert(ids: list[str], documents: list[str], embeddings: list[list[float]],
               metadatas: list[dict]) -> None:
    """写入/更新向量（documents/metadatas 用于同步内存索引中的内容镜像）。"""
    if not ids:
        return
    with _LOCK:
        with SyncSessionLocal() as db:
            stmt = sqlite_insert(VectorEmbedding).values(
                [
                    {"chunk_id": cid, "embedding": _vec_bytes(vec), "dim": len(vec)}
                    for cid, vec in zip(ids, embeddings)
                ]
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[VectorEmbedding.chunk_id],
                set_={"embedding": stmt.excluded.embedding, "dim": stmt.excluded.dim},
            )
            db.execute(stmt)
            db.commit()
        for cid, content, vec, meta in zip(ids, documents, embeddings, metadatas):
            _INDEX[cid] = {
                "vec": np.asarray(vec, dtype=np.float32),
                "content": content,
                "meta": meta,
            }
        _rebuild_matrix()


def upsert_chunks(chunks: list[dict]) -> None:
    """便捷入口：文本 → 调用方未预计算向量时现场 embedding 后写入。"""
    if not chunks:
        return
    client = get_embeddings()
    raw_upsert(
        ids=[c["id"] for c in chunks],
        documents=[c["content"] for c in chunks],
        embeddings=client.embed_documents([c["content"] for c in chunks]),
        metadatas=[c["meta"] for c in chunks],
    )


def delete_chunks(chunk_ids: list[str]) -> None:
    if not chunk_ids:
        return
    with _LOCK:
        with SyncSessionLocal() as db:
            db.execute(delete(VectorEmbedding).where(VectorEmbedding.chunk_id.in_(chunk_ids)))
            db.commit()
        for cid in chunk_ids:
            _INDEX.pop(cid, None)
        _rebuild_matrix()


def clear_collection() -> None:
    """清空全部向量（全量重向量化前使用）。"""
    with _LOCK:
        with SyncSessionLocal() as db:
            db.execute(delete(VectorEmbedding))
            db.commit()
        _INDEX.clear()
        _rebuild_matrix()


def collection_count() -> int:
    with _LOCK:
        return len(_INDEX)


def db_vector_count() -> int:
    """DB 中的向量行数（与 chunks 行数做一致性校验用）。"""
    with SyncSessionLocal() as db:
        return len(db.execute(select(VectorEmbedding.chunk_id)).all())


def db_chunk_count() -> int:
    """DB 中的 chunk 行数。"""
    with SyncSessionLocal() as db:
        return len(db.execute(select(Chunk.id)).all())


# ---------------------------------------------------------------- 检索

def similarity_search_with_scores(
    query: str, k: int, query_embedding: list[float] | None = None
) -> list[tuple[dict, float]]:
    """向量检索：embed 查询 → 内存矩阵余弦相似度 → top-k。

    :param query_embedding: 调用方预计算的查询向量（省一次 embedding 网络调用）
    :return: [(chunk 信息 {chunk_id, content, meta}, 相似度 0..1)]
    """
    if query_embedding is not None:
        q = np.asarray(query_embedding, dtype=np.float32)
    else:
        q = np.asarray(get_embeddings().embed_query(query), dtype=np.float32)
    q_norm = np.linalg.norm(q)
    if q_norm == 0:
        return []
    q = q / q_norm

    with _LOCK:
        if _MATRIX is None:
            return []
        scores = _MATRIX @ q  # (N,)
        k_eff = min(k, len(scores))
        top_idx = np.argpartition(scores, -k_eff)[-k_eff:]
        top_idx = top_idx[np.argsort(-scores[top_idx])]
        out = []
        for i in top_idx:
            cid = _IDS[i]
            item = _INDEX[cid]
            out.append(
                (
                    {"chunk_id": cid, "content": item["content"], "meta": item["meta"]},
                    float(scores[i]),
                )
            )
        return out
