"""知识库文档、分块与摄入任务模型。

设计要点：SQLite 中的 chunks 表为权威数据源（引文展示、BM25 重建不依赖向量库），
Chroma 只存向量作为检索镜像；分块 id 即 Chroma 中的文档 id（chunk:{uuid}）。
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.common import utcnow

# 文档摄入状态机
DOC_UPLOADED = "uploaded"
DOC_PARSING = "parsing"
DOC_CHUNKING = "chunking"
DOC_EMBEDDING = "embedding"
DOC_INDEXING = "indexing"
DOC_READY = "ready"
DOC_FAILED = "failed"

# 任务状态
JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_SUCCEEDED = "succeeded"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"

# 任务类型
JOB_INGEST = "ingest"
JOB_REBUILD = "rebuild"
JOB_DELETE = "delete"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))  # 原始文件名（保留中文）
    stored_path: Mapped[str] = mapped_column(String(500))  # data/uploads/ 下 uuid 前缀路径（防路径穿越）
    file_type: Mapped[str] = mapped_column(String(10))  # pdf|docx|xlsx|md|txt
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)  # 内容去重
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=DOC_UPLOADED)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # uuid4().hex
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)  # 文档内顺序
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {page, sheet, title, ...}
    token_count: Mapped[int] = mapped_column(Integer, default=0)

    document: Mapped[Document] = relationship(back_populates="chunks")


class VectorEmbedding(Base):
    """chunk 向量（float32 原始字节，1024 维 ≈ 4KB/条）。

    向量检索采用自研轻量实现：SQLite 持久化 + numpy 内存矩阵做余弦相似度检索，
    万级 chunk 查询为毫秒级。生产环境替换方案：Milvus / Qdrant（HNSW 索引）。
    """

    __tablename__ = "vector_embeddings"

    chunk_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[bytes] = mapped_column(LargeBinary)  # np.float32.tobytes()
    dim: Mapped[int] = mapped_column(Integer, default=1024)


class IngestJob(Base):
    """摄入任务：单文档摄入 / 索引重建 / 删除，worker 线程池执行并回写进度。"""

    __tablename__ = "ingest_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    job_type: Mapped[str] = mapped_column(String(20), default=JOB_INGEST)
    status: Mapped[str] = mapped_column(String(20), default=JOB_QUEUED)
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0-100
    stage: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 当前阶段名
    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    done_steps: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
