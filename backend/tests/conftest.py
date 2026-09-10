"""测试夹具：每个测试用例使用独立的临时 SQLite 库，互不干扰。"""
import os

# 必须在导入 app 之前设置：关闭限流（见 app/core/rate_limit.py 的 enabled 回调）
os.environ.setdefault("APP_ENV", "test")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app


@pytest.fixture
async def db_session(client):
    """临时库的独立会话（测试中直接插入/查询数据用）。"""
    from app.database import AsyncSessionLocal

    # 复用 override 中的工厂：直接重建一个指向同一临时库的 session
    engine = create_async_engine(client._engine_url)
    session_local = async_sessionmaker(engine, expire_on_commit=False)
    async with session_local() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def client(tmp_path):
    """返回指向临时库的 httpx 异步客户端（ASGITransport 不触发 lifespan，由本夹具建表）。"""
    from app import models  # noqa: F401 确保模型已注册

    db_url = f"sqlite+aiosqlite:///{tmp_path.as_posix()}/test.db"
    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_local = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with session_local() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c._engine_url = db_url  # 供 db_session 夹具复用
        yield c

    app.dependency_overrides.clear()
    await engine.dispose()


async def create_user(session, username: str, password: str = "test123456", role: str = "user"):
    """直接向临时库插入用户，返回 ORM 对象。"""
    from app.core.security import hash_password
    from app.models import User

    user = User(username=username, password_hash=hash_password(password), role=role)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user
