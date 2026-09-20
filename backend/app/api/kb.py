"""知识库管理路由（仅管理员）。"""
from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_admin
from app.models import User
from app.schemas.kb import (
    ChunkPreview,
    DocumentDetailOut,
    DocumentOut,
    JobOut,
    UploadResult,
)
from app.services import kb_service

router = APIRouter(prefix="/kb", tags=["知识库管理"])


@router.get("/documents")
async def list_documents(
    status: str | None = Query(default=None),
    file_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await kb_service.list_documents(db, status, file_type, page, page_size)


@router.post("/documents", response_model=UploadResult)
async def upload_documents(
    files: list[UploadFile] = File(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """多文件上传：去重 → 立即返回任务列表，摄入在后台线程池执行。"""
    return await kb_service.upload_documents(db, files, admin)


@router.get("/documents/{document_id}", response_model=DocumentDetailOut)
async def get_document(
    document_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    doc, chunks = (await kb_service.get_document_with_chunks(db, document_id)).values()
    # 不能直接 model_validate(doc)：from_attributes 会读取 ORM 的 chunks 关系，
    # 在 async session 下触发懒加载报 MissingGreenlet。先按纯字段模型展开，再手动挂 chunks。
    out = DocumentDetailOut(
        **DocumentOut.model_validate(doc).model_dump(),
        chunks=[ChunkPreview.model_validate(c) for c in chunks],
    )
    return out


@router.delete("/documents/{document_id}", response_model=JobOut)
async def delete_document(
    document_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """事务性删除：Chroma 镜像 + SQLite 级联 + 物理文件，后台执行。"""
    job = await kb_service.delete_document(db, document_id, admin)
    return job


@router.post("/rebuild-index", response_model=JobOut)
async def rebuild_index(
    re_embed: bool = Query(default=False),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """重建 BM25 索引；re_embed=true 时全量重向量化。"""
    return await kb_service.rebuild_index(db, admin, re_embed)


@router.get("/ingest-jobs")
async def list_jobs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await kb_service.list_jobs(db, page, page_size)


@router.get("/ingest-jobs/{job_id}", response_model=JobOut)
async def get_job(
    job_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """任务进度轮询（前端 1s 间隔）。"""
    return await kb_service.get_job(db, job_id)


class DebugRetrieveIn(BaseModel):
    query: str


@router.post("/debug/retrieve")
async def debug_retrieve(
    body: DebugRetrieveIn,
    _admin: User = Depends(require_admin),
):
    """检索调试：展示 向量/BM25/RRF/rerank 四层检索结果与耗时（不调 LLM）。"""
    return await kb_service.debug_retrieve(body.query)
