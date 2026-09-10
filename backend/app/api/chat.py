"""问答路由：SSE 流式问答 / 重新生成 / 停止。"""
import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.config import settings
from app.core.rate_limit import limiter
from app.dependencies import get_current_user
from app.models import User
from app.schemas.chat import ChatRequest
from app.services import chat_service
from app.utils.sse import heartbeat

router = APIRouter(prefix="/chat", tags=["问答"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",  # 生产 nginx 场景防缓冲
    "Connection": "keep-alive",
}


def _sse_response(gen):
    """把事件生成器与心跳合并为 SSE 响应。

    队列模式：主生成器事件优先即时送达；空闲超过 15s 时插入心跳注释帧
    （防代理超时断连）；主流程结束（None 哨兵）即关闭连接。
    """
    async def merged():
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)

        async def produce():
            try:
                async for frame in gen:
                    await queue.put(frame)
                await queue.put(None)  # 正常结束哨兵
            except Exception as e:  # noqa: BLE001
                await queue.put(("__error__", e))

        async def beat():
            while True:
                await asyncio.sleep(15)
                await queue.put(": heartbeat\n\n")

        producer = asyncio.create_task(produce())
        beater = asyncio.create_task(beat())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, tuple) and item and item[0] == "__error__":
                    raise item[1]
                yield item
        finally:
            beater.cancel()
            if not producer.done():
                producer.cancel()

    return StreamingResponse(
        merged(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/models")
async def available_models(user: User = Depends(get_current_user)):
    """可用模型列表（前端切换框动态加载）。"""
    items = [{"name": settings.llm_model, "label": f"{settings.llm_model}（默认）"}]
    if settings.llm_model_strong and settings.llm_model_strong != settings.llm_model:
        items.append({"name": settings.llm_model_strong, "label": f"{settings.llm_model_strong}（高质量）"})
    return items


@router.post("")
@limiter.limit(settings.rate_limit_chat)
async def chat(
    request: Request,
    body: ChatRequest,
    user: User = Depends(get_current_user),
):
    """流式问答：SSE 事件序列 meta → token* → citations → done。

    注意：不使用请求级 DB 依赖——流式生成持续数十秒，请求级 session 会一直
    占用连接，100 并发下耗尽连接池（压测实测）。DB 操作由 service 内部用
    独立短 session 完成。
    """
    return _sse_response(chat_service.stream_chat(user, body))


@router.post("/messages/{message_id}/regenerate")
async def regenerate(
    message_id: int,
    user: User = Depends(get_current_user),
):
    """重新生成：删除旧回答及之后消息，以同一问题重新流式生成。"""
    return _sse_response(chat_service.regenerate(user, message_id))


@router.post("/messages/{message_id}/stop")
async def stop(
    message_id: int,
    user: User = Depends(get_current_user),
):
    """停止生成兜底：标记消息为中断（主路径为前端 Abort + 服务端断连检测）。"""
    await chat_service.mark_interrupted(user, message_id)
    return {"message": "已停止"}
