"""数据库引擎与会话管理。

设计要点：
- async engine（aiosqlite）：FastAPI 请求路径使用，支持流式场景下的事件循环友好 I/O
- sync engine：摄入 worker 线程专用（SQLite 连接对象不能跨线程共享，必须独立引擎）
- SQLite 打开 WAL + busy_timeout + 外键约束，缓解并发写锁
"""
from collections.abc import AsyncGenerator

from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


def _absolutize_url(url: str) -> str:
    """把 sqlite URL 中的相对路径解析为绝对路径，避免 CWD 漂移。"""
    if not url.startswith("sqlite"):
        return url
    prefix, sep, raw_path = url.partition("///")
    if not sep:
        return url
    abs_path = settings.resolve_path(raw_path).as_posix()
    return prefix + sep + abs_path


_DATABASE_URL = _absolutize_url(settings.database_url)
settings.resolve_path(settings.database_url.split("///")[-1]).parent.mkdir(
    parents=True, exist_ok=True
)


def _set_sqlite_pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    # 压测实测：100 并发写入时 5s 不够（出现 database is locked），提高到 15s
    cursor.execute("PRAGMA busy_timeout=15000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# 异步引擎：FastAPI 请求路径。
# 连接池调参依据（100 并发压测）：默认 pool_size=5/max_overflow=10 会在
# 长耗时请求（LLM 生成数十秒）下耗尽；pool_timeout 从 30s 降到 10s 快速失败，
# 避免请求长时间挂起。SQLite 本地文件场景下 50 连接上限是安全的。
engine = create_async_engine(
    _DATABASE_URL,
    echo=False,
    pool_size=20,
    max_overflow=30,
    pool_timeout=10,
)
event.listens_for(engine.sync_engine, "connect")(_set_sqlite_pragmas)

# 同步引擎：摄入 worker 线程专用
sync_engine = create_engine(_DATABASE_URL.replace("+aiosqlite", ""), echo=False)
event.listens_for(sync_engine, "connect")(_set_sqlite_pragmas)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
SyncSessionLocal = sessionmaker(sync_engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：请求级异步会话。"""
    async with AsyncSessionLocal() as session:
        yield session
