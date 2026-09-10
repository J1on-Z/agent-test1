"""会话管理路由（认证用户，仅本人数据）。"""
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas.conversation import ConversationOut, MessageListOut, RenameIn
from app.services import conversation_service

router = APIRouter(prefix="/conversations", tags=["会话"])


@router.get("")
async def list_conversations(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """当前用户会话列表（按更新时间倒序）。"""
    return await conversation_service.list_conversations(db, user, page, page_size)


@router.post("", response_model=ConversationOut)
async def create_conversation(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """新建空会话（标题由首条提问自动生成）。"""
    return await conversation_service.create_conversation(db, user)


@router.get("/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await conversation_service._get_owned_conversation(db, user.id, conversation_id)


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def rename_conversation(
    conversation_id: int,
    body: RenameIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await conversation_service.rename_conversation(db, user, conversation_id, body.title)


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await conversation_service.delete_conversation(db, user, conversation_id)
    return {"message": "会话已删除"}


@router.get("/{conversation_id}/messages", response_model=MessageListOut)
async def list_messages(
    conversation_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """历史消息（重新进入会话时恢复，含引文卡片数据）。"""
    return await conversation_service.list_messages(db, user, conversation_id, page, page_size)


@router.get("/{conversation_id}/export")
async def export_conversation(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """导出会话为 Markdown（含引用附录）。"""
    md, filename = await conversation_service.export_conversation(db, user, conversation_id)
    from urllib.parse import quote

    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
