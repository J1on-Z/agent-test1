"""知识库管理业务：上传（去重/校验）→ 任务提交；文档/任务查询；删除；重建。"""
import logging
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import BizError
from app.models import Chunk, Document, IngestJob, User
from app.models.common import utcnow
from app.services.ingest.jobs import submit_delete, submit_ingest, submit_rebuild
from app.utils.hashing import sha256_file

logger = logging.getLogger(__name__)


async def _save_upload(file: UploadFile) -> Path:
    """保存上传文件：uuid 前缀重命名，防路径穿越与重名冲突。"""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in settings.allowed_ext_list:
        raise BizError("bad_extension", f"不支持的文件类型 {ext}（允许: {settings.allowed_extensions}）")
    upload_dir = settings.upload_path
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored = upload_dir / f"{uuid.uuid4().hex}{ext}"
    size = 0
    with open(stored, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_upload_size_mb * 1024 * 1024:
                stored.unlink(missing_ok=True)
                raise BizError("file_too_large", f"文件超过 {settings.max_upload_size_mb}MB 限制")
            f.write(chunk)
    return stored


async def upload_documents(db: AsyncSession, files: list[UploadFile], admin: User) -> dict:
    """多文件上传：去重 → 入库 → 提交后台摄入任务，立即返回。"""
    succeeded, skipped, job_ids = 0, [], []
    for file in files:
        filename = file.filename or "unnamed"
        try:
            stored = await _save_upload(file)
            file_hash = sha256_file(stored)
            file_type = stored.suffix.lstrip(".").lower()
            file_size = stored.stat().st_size

            # 内容去重：同一 sha256 且未失败/未删除 → 跳过
            dup = await db.scalar(
                select(Document).where(
                    Document.sha256 == file_hash,
                    Document.status.in_(["uploaded", "parsing", "chunking", "embedding", "indexing", "ready"]),
                )
            )
            if dup is not None:
                stored.unlink(missing_ok=True)
                skipped.append({"filename": filename, "reason": f"与已有文档《{dup.filename}》内容重复"})
                continue

            doc = Document(
                filename=filename,
                stored_path=str(stored),
                file_type=file_type,
                file_size=file_size,
                sha256=file_hash,
                uploaded_by=admin.id,
                status="uploaded",
            )
            db.add(doc)
            await db.commit()
            await db.refresh(doc)
            job = submit_ingest(doc.id, admin.id)
            job_ids.append(job.id)
            succeeded += 1
        except BizError as e:
            skipped.append({"filename": filename, "reason": e.message})
        except Exception as e:  # noqa: BLE001
            logger.exception("上传处理异常: %s", filename)
            skipped.append({"filename": filename, "reason": f"处理异常: {e}"})
    return {"total": len(files), "succeeded": succeeded, "skipped": skipped, "jobs": job_ids}


async def list_documents(
    db: AsyncSession,
    status: str | None = None,
    file_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    stmt = select(Document).order_by(Document.id.desc())
    if status:
        stmt = stmt.where(Document.status == status)
    if file_type:
        stmt = stmt.where(Document.file_type == file_type)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = list((await db.scalars(stmt.offset((page - 1) * page_size).limit(page_size))).all())
    return {"total": total, "items": rows, "page": page, "page_size": page_size}


async def get_document(db: AsyncSession, document_id: int) -> Document:
    doc = await db.get(Document, document_id)
    if doc is None:
        raise BizError("not_found", "文档不存在", 404)
    return doc


async def get_document_with_chunks(db: AsyncSession, document_id: int, preview: int = 10) -> dict:
    doc = await get_document(db, document_id)
    chunks = list(
        (
            await db.scalars(
                select(Chunk)
                .where(Chunk.document_id == document_id)
                .order_by(Chunk.chunk_index)
                .limit(preview)
            )
        ).all()
    )
    return {"document": doc, "chunks": chunks}


async def delete_document(db: AsyncSession, document_id: int, admin: User) -> IngestJob:
    await get_document(db, document_id)
    return submit_delete(document_id, admin.id)


async def rebuild_index(db: AsyncSession, admin: User, re_embed: bool = False) -> IngestJob:
    return submit_rebuild(admin.id, re_embed=re_embed)


async def list_jobs(db: AsyncSession, page: int = 1, page_size: int = 20) -> dict:
    stmt = select(IngestJob).order_by(IngestJob.id.desc())
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = list((await db.scalars(stmt.offset((page - 1) * page_size).limit(page_size))).all())
    return {"total": total, "items": rows, "page": page, "page_size": page_size}


async def get_job(db: AsyncSession, job_id: int) -> IngestJob:
    job = await db.get(IngestJob, job_id)
    if job is None:
        raise BizError("not_found", "任务不存在", 404)
    return job


async def load_all_chunks_sync() -> None:
    """把 SQLite 全量 chunk 灌入内存 BM25（服务启动/变更后调用；跑在线程池避免阻塞循环）。"""
    import asyncio

    from app.services.ingest.pipeline import _rebuild_bm25

    await asyncio.to_thread(_rebuild_bm25)


def _hit_view(item: dict, score: float) -> dict:
    """调试端点的命中条目视图。"""
    meta = item.get("meta") or {}
    return {
        "chunk_id": item["chunk_id"],
        "doc_name": meta.get("doc_name", "?"),
        "title": meta.get("doc_title") or meta.get("title") or "",
        "score": round(score, 4),
        "snippet": (item.get("content") or "")[:120],
    }


async def debug_retrieve(query: str) -> dict:
    """检索调试：返回 向量 → BM25 → RRF 融合 → rerank 四层结果与耗时，不调 LLM。"""
    import asyncio
    import time

    from app.services.retrieval.hybrid import hybrid_retrieve
    from app.services.retrieval.reranker import rerank_candidates

    t0 = time.perf_counter()
    fused, detail = await hybrid_retrieve(query)
    t1 = time.perf_counter()
    reranked = []
    rerank_ms = None
    if settings.rerank_enabled and fused:
        reranked = await asyncio.to_thread(rerank_candidates, query, fused, settings.rerank_top_n)
        t2 = time.perf_counter()
        rerank_ms = int((t2 - t1) * 1000)
    return {
        "query": query,
        "rerank_enabled": settings.rerank_enabled,
        "rerank_threshold": settings.rerank_score_threshold,
        "vector_hits": [_hit_view(item, s) for item, s in detail["vector"]],
        "bm25_hits": [_hit_view(item, s) for item, s in detail["bm25"]],
        "fused": [_hit_view(c, detail["rrf_scores"][c["chunk_id"]]) for c in fused],
        "reranked": [_hit_view(c, c["score"]) for c in reranked],
        "latency_ms": {
            **detail["latency_ms"],
            "rerank": rerank_ms,
            "total": int((time.perf_counter() - t0) * 1000),
        },
    }
