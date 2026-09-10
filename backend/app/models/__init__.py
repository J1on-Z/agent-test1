"""ORM 模型汇总：main.py 建表前 import 本模块确保全部模型注册到 metadata。"""
from app.models.common import utcnow
from app.models.conversation import (
    MSG_INTERRUPTED,
    MSG_NORMAL,
    ROLE_ASSISTANT,
    ROLE_USER,
    Conversation,
    Message,
)
from app.models.document import (
    DOC_CHUNKING,
    DOC_EMBEDDING,
    DOC_FAILED,
    DOC_INDEXING,
    DOC_PARSING,
    DOC_READY,
    DOC_UPLOADED,
    JOB_CANCELLED,
    JOB_DELETE,
    JOB_FAILED,
    JOB_INGEST,
    JOB_QUEUED,
    JOB_REBUILD,
    JOB_RUNNING,
    JOB_SUCCEEDED,
    Chunk,
    Document,
    IngestJob,
    VectorEmbedding,
)
from app.models.stats import RequestLog, SemanticCacheEntry
from app.models.user import RefreshToken, User

__all__ = [
    "utcnow",
    # 会话
    "MSG_INTERRUPTED",
    "MSG_NORMAL",
    "ROLE_ASSISTANT",
    "ROLE_USER",
    "Conversation",
    "Message",
    # 文档
    "DOC_CHUNKING",
    "DOC_EMBEDDING",
    "DOC_FAILED",
    "DOC_INDEXING",
    "DOC_PARSING",
    "DOC_READY",
    "DOC_UPLOADED",
    "JOB_CANCELLED",
    "JOB_DELETE",
    "JOB_FAILED",
    "JOB_INGEST",
    "JOB_QUEUED",
    "JOB_REBUILD",
    "JOB_RUNNING",
    "JOB_SUCCEEDED",
    "Chunk",
    "Document",
    "IngestJob",
    "VectorEmbedding",
    # 统计
    "RequestLog",
    "SemanticCacheEntry",
    # 用户
    "RefreshToken",
    "User",
]
