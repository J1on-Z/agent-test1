"""模型公共工具：统一 UTC 时间（SQLite DateTime 列按 naive UTC 存储，前端负责本地化显示）。"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
