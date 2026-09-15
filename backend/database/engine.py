# backend/database/engine.py
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend.core.config import settings
from backend.database.tenant import bind_tenant_context

engine = create_async_engine(
    settings.POSTGRES_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_pre_ping=True,       # проверять соединение перед использованием
    echo=False,               # SQL echo off — use pgAdmin/Jaeger for query tracing
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,   # объекты живут после commit
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency для получения async DB-сессии.

    FIX: авто-коммит убран. Каждый write-endpoint ОБЯЗАН явно вызвать
    await db.commit() после изменений. Это предотвращает молчаливое
    сохранение случайных .add() в GET-запросах.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_db_session(
    org_id: str | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager для фоновых задач (не FastAPI endpoints).
    Если передан org_id, Session привязана к tenant на всех её транзакциях.
    Без org_id сессия остаётся unscoped; это не разрешение обходить RLS.

    Usage (TZ-04 _execute_waves, TZ-02 sync_device_status_to_db):
        async with get_db_session(org_id=str(batch.org_id)) as db:
            await db.get(TaskBatch, batch_id)
    """
    async with AsyncSessionLocal() as session:
        if org_id is not None:
            await bind_tenant_context(session, org_id)
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
