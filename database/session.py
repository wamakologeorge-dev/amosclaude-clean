"""Database engine and transaction helpers shared across Amosclaud services."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


def database_url() -> str:
    configured = os.getenv("AMOSCLAUD_PLATFORM_DATABASE_URL", "").strip()
    if configured:
        return configured
    data_dir = Path(os.getenv("AMOSCLAUD_DATA_DIR", "./data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(data_dir / 'amosclaud-platform.db').resolve()}"


_ENGINE = create_engine(
    database_url(),
    future=True,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if database_url().startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=_ENGINE, autoflush=False, autocommit=False, expire_on_commit=False)


def create_database() -> None:
    Base.metadata.create_all(bind=_ENGINE)


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
