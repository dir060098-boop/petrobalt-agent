"""
Async SQLAlchemy engine + session factory.
Используется для прямых SQL-запросов к PostgreSQL (Supabase).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import get_settings

logger = logging.getLogger(__name__)

_engine = None
_session_factory = None


def _get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        if not settings.db_configured:
            raise RuntimeError(
                "DATABASE_URL не задан. "
                "Заполните .env: DATABASE_URL=postgresql+asyncpg://..."
            )
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.app_env == "development",
            poolclass=NullPool,   # Supabase: pooler управляет соединениями сам
        )
        logger.info("DB engine создан: %s", settings.database_url.split("@")[-1])
    return _engine


def _get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=_get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Контекстный менеджер для получения DB-сессии."""
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends dependency."""
    async with get_db() as session:
        yield session
