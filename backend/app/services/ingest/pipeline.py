"""摄入流水线：解析 → 分块 → 向量化 → 双写（SQLite 权威 + Chroma 镜像）→ 重建 BM25。

在 jobs 线程池的 worker 线程中执行，全程使用同步 engine 会话。
进度按阶段加权回写 ingest_jobs（前端 1s 轮询展示），失败单文档可读、可重试。
"""
import logging
import uuid
from pathlib import Path

from sqlalchemy import delete, select

from app.config import settings
from app.database import SyncSessionLocal
from app.models import (
    DOC_CHUNKING,
    DOC_EMBEDDING,
    DOC_FAILED,
    DOC_INDEXING,
    DOC_PARSING,
    DOC_READY,
    JOB_FAILED,
    JOB_RUNNING,
    JOB_SUCCEEDED,
    Chunk,
    Document,
    IngestJob,
)
from app.models.common import utcnow
from app.services.ingest.chunker import chunk_sections
from app.services.ingest.parsers import ParseError, parse_file
from app.services.llm.embeddings import get_embeddings
from app.services.retrieval import vector_store
from app.services.retrieval.bm25 import rebuild_from_rows_sync

logger = logging.getLogger(__name__)

# 阶段权重（合计 100）：解析 10 + 分块 10 + 向量化 60 + 索引 20
_STAGE_WEIGHTS = {
    DOC_PARSING: 10,
    DOC_CHUNKING: 10,
    DOC_EMBEDDING: 60,
    DOC_INDEXING: 20,
}
_STAGE_NAMES = {
    DOC_PARSING: "解析文档",
    DOC_CHUNKING: "文本分块",
    DOC_EMBEDDING: "向量化",
    DOC_INDEXING: "写入索引",
}
_STAGE_ORDER = [DOC_PARSING, DOC_CHUNKING, DOC_EMBEDDING, DOC_INDEXING]


def _update_job(db, job: IngestJob, progress: float, stage: str | None = None,
                message: str | None = None) -> None:
    job.progress = min(progress, 100.0)
    if stage:
        job.stage = _STAGE_NAMES.get(stage, stage)
    if message:
        job.message = message
    db.commit()


def _fail_job(db, job: IngestJob, error: str) -> None:
    job.status = JOB_FAILED
    job.message = error
    job.finished_at = utcnow()
    db.commit()
    logger.warning("任务 %s 失败: %s", job.id, error)


def _stage_progress(stage: str, done_ratio: float) -> float:
    """当前阶段内进度 + 已完成阶段的固定权重。"""
    base = sum(_STAGE_WEIGHTS[s] for s in _STAGE_ORDER[: _STAGE_ORDER.index(stage)])
    return base + _STAGE_WEIGHTS[stage] * max(0.0, min(done_ratio, 1.0))


# ---------------------------------------------------------------- 摄入主流程

def run_ingest(job_id: int) -> None:
    """单文档摄入（worker 线程）。"""
    with SyncSessionLocal() as db:
        job = db.get(IngestJob, job_id)
        if job is None or job.document_id is None:
            return
        document = db.get(Document, job.document_id)
        if document is None:
            _fail_job(db, job, "文档不存在")
            return
        job.status = JOB_RUNNING
        db.commit()
        stored_path = Path(document.stored_path)

        try:
            # ---- 阶段 1：解析 ----
            document.status = DOC_PARSING
            _update_job(db, job, 0, DOC_PARSING)
            try:
                sections, title = parse_file(stored_path, document.file_type)
            except ParseError as e:
                document.status = DOC_FAILED
                document.error = e.message
                _fail_job(db, job, e.message)
                return
            total_chars = sum(len(s.text) for s in sections)
            document.category = title[:50] or None

            # ---- 阶段 2：分块 ----
            document.status = DOC_CHUNKING
            _update_job(db, job, _stage_progress(DOC_CHUNKING, 0), DOC_CHUNKING)
            chunks = chunk_sections(sections, title, document.filename)
            if not chunks:
                raise ParseError("分块后没有可用内容")

            # ---- 阶段 3：向量化（分批，容忍单批失败） ----
            document.status = DOC_EMBEDDING
            _update_job(db, job, _stage_progress(DOC_EMBEDDING, 0), DOC_EMBEDDING)
            embeddings_client = get_embeddings()
            failed_batches = 0
            batch_size = settings.embedding_batch_size
            for i in range(0, len(chunks), batch_size):
                batch = chunks[i : i + batch_size]
                try:
                    batch_vectors = embeddings_client.embed_documents([c["content"] for c in batch])
                except Exception as e:  # noqa: BLE001
                    failed_batches += 1
                    logger.warning("向量化批次 %d 失败（已跳过）: %s", i // batch_size, e)
                    for c in batch:
                        c["embedding"] = None
                else:
                    for c, vec in zip(batch, batch_vectors):
                        c["embedding"] = vec
                _update_job(db, job, _stage_progress(DOC_EMBEDDING, (i + batch_size) / len(chunks)), DOC_EMBEDDING)

            valid_chunks = [c for c in chunks if c["embedding"] is not None]
            if not valid_chunks:
                raise RuntimeError("全部批次向量化失败，请检查 embedding 服务后重试")

            # ---- 阶段 4：双写与索引 ----
            document.status = DOC_INDEXING
            _update_job(db, job, _stage_progress(DOC_INDEXING, 0), DOC_INDEXING)
            chunk_rows = []
            for idx, c in enumerate(valid_chunks):
                chunk_id = uuid.uuid4().hex
                row = Chunk(
                    id=chunk_id,
                    document_id=document.id,
                    chunk_index=idx,
                    content=c["content"],
                    meta={**c["meta"], "title": title},
                    token_count=c["token_count"],
                )
                db.add(row)
                chunk_rows.append({"row": row, "chunk": c, "chunk_id": chunk_id})
            db.commit()

            # 向量持久化（用已算好的向量，避免重复 embedding）
            if chunk_rows:
                vector_store.raw_upsert(
                    ids=[r["chunk_id"] for r in chunk_rows],
                    documents=[r["chunk"]["content"] for r in chunk_rows],
                    embeddings=[r["chunk"]["embedding"] for r in chunk_rows],
                    metadatas=[r["chunk"]["meta"] for r in chunk_rows],
                )

            document.chunk_count = len(valid_chunks)
            document.char_count = total_chars
            document.status = DOC_READY
            document.indexed_at = utcnow()
            if failed_batches:
                document.error = f"{failed_batches} 个批次向量化失败，已跳过"
            job.status = JOB_SUCCEEDED
            job.progress = 100
            job.message = f"完成：{len(valid_chunks)} 个分块" + (f"，{failed_batches} 批失败已跳过" if failed_batches else "")
            job.finished_at = utcnow()
            db.commit()

            # BM25 重建（读全量 chunk，保证关键词检索覆盖新文档）
            _rebuild_bm25()

        except Exception as e:  # noqa: BLE001
            db.rollback()
            document = db.get(Document, document.id)
            if document is not None:
                document.status = DOC_FAILED
                document.error = str(e)[:500]
            job = db.get(IngestJob, job_id)
            if job is not None:
                job.status = JOB_FAILED
                job.message = str(e)[:500]
                job.finished_at = utcnow()
            db.commit()
            logger.exception("文档 %s 摄入失败", document.filename if document else "?")


# ---------------------------------------------------------------- 删除 / 重建

def run_delete(document_id: int) -> None:
    """事务性删除：Chroma 镜像 → SQLite 级联 → 物理文件 → 重建 BM25。"""
    with SyncSessionLocal() as db:
        document = db.get(Document, document_id)
        if document is None:
            return
        chunk_ids = list(
            db.scalars(select(Chunk.id).where(Chunk.document_id == document_id))
        )
        # 1. Chroma 镜像
        try:
            vector_store.delete_chunks(chunk_ids)
        except Exception as e:  # noqa: BLE001
            logger.warning("Chroma 删除失败（不影响 SQLite 删除）: %s", e)
        # 2. SQLite 级联删除
        db.delete(document)
        db.commit()
        # 3. 物理文件
        try:
            Path(document.stored_path).unlink(missing_ok=True)
        except OSError as e:
            logger.warning("删除物理文件失败: %s", e)
        # 4. BM25 重建
        _rebuild_bm25()


def run_rebuild(re_embed: bool = False) -> None:
    """重建索引：默认仅重建 BM25；re_embed=True 时全量重向量化。"""
    if re_embed:
        with SyncSessionLocal() as db:
            rows = list(db.execute(select(Chunk)).scalars())
            if rows:
                vector_store.clear_collection()
                embeddings_client = get_embeddings()
                batch_size = settings.embedding_batch_size
                texts = [r.content for r in rows]
                ids = [r.id for r in rows]
                metadatas = [
                    {k: (v if isinstance(v, (str, int, float, bool)) else str(v)) for k, v in (r.meta or {}).items()}
                    for r in rows
                ]
                for i in range(0, len(texts), batch_size):
                    vecs = embeddings_client.embed_documents(texts[i : i + batch_size])
                    vector_store.raw_upsert(
                        ids=ids[i : i + batch_size],
                        documents=texts[i : i + batch_size],
                        embeddings=vecs,
                        metadatas=metadatas[i : i + batch_size],
                    )
        logger.info("全量重向量化完成")
    _rebuild_bm25()


def _rebuild_bm25() -> None:
    with SyncSessionLocal() as db:
        rows = list(db.execute(select(Chunk.id, Chunk.content, Chunk.meta)).all())
        rebuild_from_rows_sync(
            [{"id": r[0], "content": r[1], "meta": r[2]} for r in rows]
        )


def mark_stale_jobs_failed() -> None:
    """服务启动时：把遗留的 running/queued 任务标记为失败（进程内队列不持久化）。"""
    with SyncSessionLocal() as db:
        stale = list(db.scalars(select(IngestJob).where(IngestJob.status.in_([JOB_RUNNING, "queued"]))).all())
        for job in stale:
            job.status = JOB_FAILED
            job.message = "服务重启，任务中断（请重新触发）"
            job.finished_at = utcnow()
        db.commit()
        if stale:
            logger.info("已将 %d 个遗留任务标记为失败", len(stale))
