"""会话管理业务：列表/创建/重命名/删除/历史消息/导出。

所有查询强制 user_id 过滤，实现多用户会话隔离（SQL 层面防越权）。
"""
import logging

from fastapi import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.models import Conversation, Message, User
from app.models.common import utcnow
from app.utils.text import truncate_title

logger = logging.getLogger(__name__)


async def _get_owned_conversation(
    db: AsyncSession, user_id: int, conversation_id: int
) -> Conversation:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user_id:
        raise BizError("not_found", "会话不存在", 404)
    return conversation


async def list_conversations(db: AsyncSession, user: User, page: int, page_size: int) -> dict:
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
    )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = list((await db.scalars(stmt.offset((page - 1) * page_size).limit(page_size))).all())
    return {"total": total, "items": rows, "page": page, "page_size": page_size}


async def create_conversation(db: AsyncSession, user: User, title: str | None = None) -> Conversation:
    conversation = Conversation(
        user_id=user.id, title=title or "新会话", message_count=0
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def rename_conversation(
    db: AsyncSession, user: User, conversation_id: int, title: str
) -> Conversation:
    conversation = await _get_owned_conversation(db, user.id, conversation_id)
    conversation.title = title.strip()[:100]
    conversation.updated_at = utcnow()
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def delete_conversation(db: AsyncSession, user: User, conversation_id: int) -> None:
    conversation = await _get_owned_conversation(db, user.id, conversation_id)
    await db.delete(conversation)  # 级联删除 messages
    await db.commit()


async def list_messages(
    db: AsyncSession, user: User, conversation_id: int, page: int, page_size: int
) -> dict:
    await _get_owned_conversation(db, user.id, conversation_id)
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
    )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = list((await db.scalars(stmt.offset((page - 1) * page_size).limit(page_size))).all())
    rows.reverse()  # 返回时间正序，前端直接渲染
    return {"total": total, "items": rows}


async def export_conversation(
    db: AsyncSession, user: User, conversation_id: int
) -> tuple[str, str]:
    """导出会话为 Markdown（含引用附录）。"""
    conversation = await _get_owned_conversation(db, user.id, conversation_id)
    messages = list(
        (
            await db.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.id)
            )
        ).all()
    )
    lines = [f"# 会话：{conversation.title}", ""]
    for m in messages:
        who = "👤 用户" if m.role == "user" else "🤖 助手"
        lines.append(f"## {who}（{m.created_at.strftime('%Y-%m-%d %H:%M')}）")
        lines.append(m.content)
        lines.append("")
        if m.citations:
            lines.append("**引用来源：**")
            for c in m.citations:
                lines.append(
                    f"- 【{c.get('index')}】《{c.get('doc_name', '?')}》"
                    + (f" 第{c['page']}页" if c.get("page") else "")
                    + f"（相关度 {c.get('score', 0):.2f}）"
                    + f"\n  > {(c.get('snippet') or '')[:150]}"
                )
            lines.append("")
    md = "\n".join(lines)
    filename = f"conversation_{conversation_id}.md"
    return md, filename


async def ensure_title(db: AsyncSession, conversation: Conversation, question: str) -> None:
    """首条提问后设置会话标题（截断 20 字）。"""
    if conversation.message_count == 0 and (conversation.title == "新会话" or not conversation.title):
        conversation.title = truncate_title(question)
        await db.commit()
