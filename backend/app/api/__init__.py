"""API 路由汇总。"""
from fastapi import APIRouter

from app.api import auth, chat, conversations, health, kb, stats

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(conversations.router)
api_router.include_router(chat.router)
api_router.include_router(kb.router)
api_router.include_router(stats.router)
