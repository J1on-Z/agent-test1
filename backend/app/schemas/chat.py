"""聊天相关请求模型。"""
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    conversation_id: int | None = None  # 空则新建会话
    question: str = Field(min_length=1, max_length=2000)
    model: str | None = None            # 留空用默认模型
    thinking: bool = False              # 思考模式开关
