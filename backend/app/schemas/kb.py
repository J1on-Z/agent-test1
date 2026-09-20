"""知识库管理相关请求/响应模型。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    file_type: str
    file_size: int
    category: str | None = None
    status: str
    chunk_count: int
    char_count: int
    error: str | None = None
    created_at: datetime
    indexed_at: datetime | None = None


class ChunkPreview(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    chunk_index: int
    content: str
    meta: dict | None = None


class DocumentDetailOut(DocumentOut):
    chunks: list[ChunkPreview] = []


class UploadSkipped(BaseModel):
    filename: str
    reason: str


class UploadResult(BaseModel):
    total: int
    succeeded: int
    skipped: list[UploadSkipped]
    jobs: list[int]


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int | None = None
    job_type: str
    status: str
    progress: float
    stage: str | None = None
    total_steps: int
    done_steps: int
    message: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
