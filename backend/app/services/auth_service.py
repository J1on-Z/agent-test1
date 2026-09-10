"""认证业务：注册/登录/刷新/登出/改密/管理员种子。"""
import logging
from datetime import datetime, timezone

import jwt as pyjwt
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import BizError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.database import AsyncSessionLocal
from app.models import RefreshToken, User
from app.models.common import utcnow

logger = logging.getLogger(__name__)


async def _issue_token_pair(db: AsyncSession, user: User) -> dict:
    """签发 access + refresh，refresh 的 jti 落库。"""
    refresh_token, jti, expires_at = create_refresh_token(user.id)
    db.add(RefreshToken(user_id=user.id, jti=jti, expires_at=expires_at))
    return {
        "access_token": create_access_token(user.id, user.username, user.role),
        "refresh_token": refresh_token,
    }


async def register(db: AsyncSession, username: str, password: str) -> User:
    error = validate_password_strength(password)
    if error:
        raise BizError("weak_password", error)
    exists = await db.scalar(select(User.id).where(User.username == username))
    if exists:
        raise BizError("username_taken", "用户名已被注册")
    user = User(username=username, password_hash=hash_password(password), role="user")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("新用户注册: %s", username)
    return user


async def login(db: AsyncSession, username: str, password: str) -> dict:
    user = await db.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(password, user.password_hash):
        raise BizError("bad_credentials", "用户名或密码错误", 401)
    if not user.is_active:
        raise BizError("user_disabled", "账号已被禁用", 403)
    user.last_login_at = utcnow()
    pair = await _issue_token_pair(db, user)
    await db.commit()
    await db.refresh(user)
    return {**pair, "user": user}


async def refresh(db: AsyncSession, refresh_token: str) -> dict:
    """refresh rotation：校验 jti 未吊销 → 吊销旧 jti → 签发新对。"""
    try:
        payload = decode_token(refresh_token, "refresh")
        user_id = int(payload["sub"])
        jti = payload["jti"]
    except (pyjwt.PyJWTError, KeyError, ValueError):
        raise BizError("bad_refresh_token", "刷新凭证无效，请重新登录", 401)

    record = await db.scalar(
        select(RefreshToken).where(RefreshToken.jti == jti)
    )
    if (
        record is None
        or record.revoked
        or record.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc)
    ):
        raise BizError("bad_refresh_token", "刷新凭证已失效，请重新登录", 401)

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise BizError("bad_refresh_token", "用户不存在或已被禁用", 401)

    record.revoked = True  # 旧 jti 立即吊销（rotation 防重放）
    pair = await _issue_token_pair(db, user)
    await db.commit()
    await db.refresh(user)
    return {**pair, "user": user}


async def logout(db: AsyncSession, refresh_token: str) -> None:
    try:
        payload = decode_token(refresh_token, "refresh")
        jti = payload["jti"]
    except (pyjwt.PyJWTError, KeyError):
        return  # 无效 token 视为已登出
    await db.execute(
        update(RefreshToken).where(RefreshToken.jti == jti).values(revoked=True)
    )
    await db.commit()


async def change_password(
    db: AsyncSession, user: User, old_password: str, new_password: str
) -> None:
    if not verify_password(old_password, user.password_hash):
        raise BizError("bad_old_password", "原密码不正确")
    error = validate_password_strength(new_password)
    if error:
        raise BizError("weak_password", error)
    if verify_password(new_password, user.password_hash):
        raise BizError("same_password", "新密码不能与原密码相同")
    user.password_hash = hash_password(new_password)
    # 改密后吊销该用户全部刷新令牌，旧登录态强制下线
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked.is_(False))
        .values(revoked=True)
    )
    await db.commit()
    logger.info("用户 %s 修改了密码", user.username)


async def ensure_admin_user() -> None:
    """启动时兜底创建管理员（admin/123456，可在页面改密）。"""
    async with AsyncSessionLocal() as db:
        admin = await db.scalar(
            select(User).where(User.username == settings.admin_username)
        )
        if admin is None:
            db.add(
                User(
                    username=settings.admin_username,
                    password_hash=hash_password(settings.admin_password),
                    role="admin",
                )
            )
            await db.commit()
            logger.info("已创建内置管理员账号: %s", settings.admin_username)
