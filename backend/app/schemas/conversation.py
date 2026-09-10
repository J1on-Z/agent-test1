"""会话与消息相关请求/响应模型。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class ConversationCreateOut(ConversationOut):
    pass


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: str
    content: str
    model: str | None = None
    citations: list | None = None
    token_usage: dict | None = None
    latency_ms: int | None = None
    ttft_ms: int | None = None
    from_cache: bool = False
    status: str
    created_at: datetime


class MessageListOut(BaseModel):
    total: int
    items: list[MessageOut]
