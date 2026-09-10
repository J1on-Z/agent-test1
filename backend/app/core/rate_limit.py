"""限流器（slowapi）：登录/聊天/全局三档限流。

key_func 优先取 JWT 中的用户 id（按用户限流），未认证请求回退到 IP。
单机内存计数；生产环境换 API 网关/Redis 令牌桶实现多实例共享计数。
"""
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings
from app.core.security import decode_token


def _key_func(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = decode_token(auth[7:], "access")
            return f"user:{payload['sub']}"
        except Exception:
            pass
    return get_remote_address(request)


# 测试环境（APP_ENV=test）关闭限流，避免用例间相互影响；导入时求值
# headers_enabled=False：避免 slowapi 要求端点签名携带 response 参数的耦合
limiter = Limiter(
    key_func=_key_func,
    default_limits=[settings.rate_limit_global],
    headers_enabled=False,
    enabled=settings.app_env != "test",
)
