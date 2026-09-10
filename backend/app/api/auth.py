"""认证路由：注册/登录/刷新/登出/改密/当前用户。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.rate_limit import limiter
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas.auth import (
    ChangePasswordIn,
    LoginIn,
    RefreshIn,
    RegisterIn,
    TokenPair,
    UserOut,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", response_model=UserOut)
@limiter.limit(settings.rate_limit_login)
async def register(
    request: Request, body: RegisterIn, db: AsyncSession = Depends(get_db)
):
    """注册（普通用户角色；管理员账号为内置种子）。"""
    return await auth_service.register(db, body.username, body.password)


@router.post("/login", response_model=TokenPair)
@limiter.limit(settings.rate_limit_login)
async def login(
    request: Request, body: LoginIn, db: AsyncSession = Depends(get_db)
):
    """登录：返回 access(30min) + refresh(7d)。"""
    return await auth_service.login(db, body.username, body.password)


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshIn, db: AsyncSession = Depends(get_db)):
    """刷新凭证：旧 refresh 旋转吊销，签发新对。"""
    return await auth_service.refresh(db, body.refresh_token)


@router.post("/logout")
async def logout(body: RefreshIn, db: AsyncSession = Depends(get_db)):
    """登出：吊销当前 refresh token。"""
    await auth_service.logout(db, body.refresh_token)
    return {"message": "已退出登录"}


@router.post("/change-password")
async def change_password(
    body: ChangePasswordIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """修改密码：校验旧密码；成功后吊销全部刷新令牌。"""
    await auth_service.change_password(db, user, body.old_password, body.new_password)
    return {"message": "密码修改成功，请重新登录"}


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    """当前用户信息（前端路由守卫/角色判断用）。"""
    return user
