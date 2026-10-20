"""异步 SQLAlchemy 引擎与会话管理"""
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def _ensure_role_column(sync_conn) -> None:
    """无迁移框架：老库 users 表缺 role 列时自动补上（SQLite/PostgreSQL 通用）。"""
    from sqlalchemy import inspect, text

    cols = [c["name"] for c in inspect(sync_conn).get_columns("users")]
    if "role" not in cols:
        sync_conn.execute(
            text("ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'user'")
        )


def _ensure_admin_role(sync_conn) -> None:
    """启动时把 ADMIN_EMAIL 对应账号自动提升为管理员。"""
    if not settings.ADMIN_EMAIL:
        return
    from sqlalchemy import text

    sync_conn.execute(
        text("UPDATE users SET role = 'admin' WHERE lower(email) = lower(:email)"),
        {"email": settings.ADMIN_EMAIL},
    )


async def init_db() -> None:
    """建表（不再创建演示用户，认证改为注册/登录）"""
    from app import models  # noqa: F401  确保模型已注册

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_role_column)
        await conn.run_sync(_ensure_admin_role)
