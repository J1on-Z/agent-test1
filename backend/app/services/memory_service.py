"""记忆服务：摘要 + 滑动窗口（自研，替代 LangChain 已 deprecated 的 Memory 类）。

- 读：窗口内最近 N 条消息原文 + 窗口外更早历史的滚动摘要
- 写：消息数超过阈值后，用 LLM 把「旧摘要 + 被挤出窗口的消息」合并为新摘要，
  异步后台执行、失败静默降级（直接截断旧摘要拼接），不影响会话主流程
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Conversation, Message
from app.models.common import utcnow
from app.services.llm.prompts import SUMMARY_PROMPT

logger = logging.getLogger(__name__)


async def get_memory_context(
    db: AsyncSession, conversation_id: int, exclude_message_id: int | None = None
) -> tuple[list[tuple[str, str]], str]:
    """组装进入 LangGraph 的记忆上下文。

    :param exclude_message_id: 排除指定消息（流式问答时排除刚写入的当前用户问题）
    :return: (窗口消息 [(role, content)], 滚动摘要)
    """
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        return [], ""
    stmt = select(Message).where(Message.conversation_id == conversation_id)
    if exclude_message_id is not None:
        stmt = stmt.where(Message.id != exclude_message_id)
    rows = list((await db.scalars(stmt.order_by(Message.id.desc()).limit(settings.memory_window_messages))).all())
    rows.reverse()  # 转为时间正序
    window = [(m.role, m.content) for m in rows]
    return window, conversation.summary or ""


async def maybe_update_summary(conversation_id: int) -> None:
    """后台任务入口（LangGraph update_summary 节点调度）：超阈值才真正执行。"""
    try:
        async with AsyncSessionLocal() as db:
            conversation = await db.get(Conversation, conversation_id)
            if conversation is None:
                return
            total = conversation.message_count
            if total <= settings.summary_trigger_messages:
                return
            await _do_summary(db, conversation)
    except Exception:  # noqa: BLE001
        logger.exception("摘要更新失败（已降级忽略）: conversation=%s", conversation_id)


async def _do_summary(db: AsyncSession, conversation: Conversation) -> None:
    """合并旧摘要与窗口外消息，生成新滚动摘要写回。"""
    window = settings.memory_window_messages
    older = list(
        (
            await db.scalars(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.id.desc())
                .offset(window)
                .limit(settings.summary_trigger_messages)
            )
        ).all()
    )
    if not older:
        return
    older.reverse()
    new_messages_text = "\n".join(f"{m.role}: {m.content[:200]}" for m in older)

    old_summary = conversation.summary or ""
    try:
        from app.services.llm.qwen import get_llm

        llm = get_llm(settings.llm_model, thinking=False)
        prompt = SUMMARY_PROMPT.format(old_summary=old_summary, new_messages=new_messages_text)
        resp = await llm.ainvoke(prompt)
        new_summary = (resp.content or "").strip()
        if not new_summary:  # 模型异常时降级为截断拼接
            new_summary = (old_summary + "\n" + new_messages_text)[-800:]
    except Exception:  # noqa: BLE001 摘要失败降级，不影响会话
        new_summary = (old_summary + "\n" + new_messages_text)[-800:]

    conversation.summary = new_summary
    conversation.summary_updated_at = utcnow()
    await db.commit()
    logger.info("会话 %s 摘要已更新（%d 字）", conversation.id, len(new_summary))
