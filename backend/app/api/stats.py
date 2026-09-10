"""统计路由（仅管理员）：总览 / 日趋势 / token / 延迟 / 缓存 / 活跃用户。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_admin
from app.models import User
from app.services import stats_service

router = APIRouter(prefix="/stats", tags=["统计"])


@router.get("/overview")
async def overview(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await stats_service.overview(db)


@router.get("/daily")
async def daily(
    days: int = Query(default=14, ge=1, le=90),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await stats_service.daily(db, days)


@router.get("/token-usage")
async def token_usage(
    days: int = Query(default=14, ge=1, le=90),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await stats_service.token_usage(db, days)


@router.get("/latency")
async def latency(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await stats_service.latency(db)


@router.get("/cache")
async def cache(
    days: int = Query(default=14, ge=1, le=90),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await stats_service.cache(db, days)


@router.get("/top-users")
async def top_users(
    limit: int = Query(default=10, ge=1, le=50),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await stats_service.top_users(db, limit)
