"""Async SQLAlchemy session for non-blocking access inside async FastAPI endpoints."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


def _async_database_url() -> str:
    configured = os.getenv("AMOSCLAUD_PLATFORM_DATABASE_URL", "").strip()
    if configured:
        if configured.startswith("postgresql+psycopg2://"):
            return configured.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
        if configured.startswith("postgresql://"):
            return configured.replace("postgresql://", "postgresql+asyncpg://", 1)
        if configured.startswith("sqlite:///"):
            return configured.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        return configured
    data_dir = Path(os.getenv("AMOSCLAUD_DATA_DIR", "./data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{(data_dir / 'amosclaud-platform.db').resolve()}"


_async_engine = create_async_engine(_async_database_url(), echo=False, pool_pre_ping=True)
AsyncSessionLocal = sessionmaker(_async_engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def async_session_scope() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
