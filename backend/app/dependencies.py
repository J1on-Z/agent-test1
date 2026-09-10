"""FastAPI 公共依赖：当前用户解析、管理员鉴权。"""
import jwt as pyjwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.core.security import decode_token
from app.database import get_db
from app.models import User

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """从 Authorization: Bearer <access token> 解析当前用户。"""
    if credentials is None:
        raise BizError("unauthorized", "未登录或凭证缺失", 401)
    try:
        payload = decode_token(credentials.credentials, "access")
        user_id = int(payload["sub"])
    except (pyjwt.PyJWTError, KeyError, ValueError):
        raise BizError("unauthorized", "登录已过期，请重新登录", 401)
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise BizError("unauthorized", "用户不存在或已被禁用", 401)
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """管理员专属接口的守卫依赖（前端路由守卫之外的第二道防线）。"""
    if user.role != "admin":
        raise BizError("forbidden", "仅管理员可访问该功能", 403)
    return user
