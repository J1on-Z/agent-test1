"""SSE（Server-Sent Events）事件帧封装。

事件约定（POST /api/chat 流式问答）：
  event: meta      会话/消息 id、模型名
  event: token     逐 token 增量
  event: citations 引文列表（生成结束后一次推送）
  event: done      usage/延迟/缓存命中标记
  event: error     失败或限流
  注释帧（: heartbeat）由心跳协程定期发送，防代理超时断连
"""
import asyncio
import json
from collections.abc import AsyncGenerator


def _frame(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_meta(**kwargs) -> str:
    return _frame("meta", kwargs)


def sse_meta_thinking(delta: str) -> str:
    """思考模式下的 reasoning 增量（前端折叠块展示）。"""
    return _frame("thinking", {"delta": delta})


def sse_token(delta: str) -> str:
    return _frame("token", {"delta": delta})


def sse_citations(citations: list) -> str:
    return _frame("citations", {"citations": citations})


def sse_done(**kwargs) -> str:
    return _frame("done", kwargs)


def sse_error(code: str, message: str) -> str:
    return _frame("error", {"code": code, "message": message})


async def heartbeat(interval: float = 15.0) -> AsyncGenerator[str, None]:
    """心跳注释帧：客户端忽略注释帧，但能保持连接活性。"""
    while True:
        await asyncio.sleep(interval)
        yield ": heartbeat\n\n"
