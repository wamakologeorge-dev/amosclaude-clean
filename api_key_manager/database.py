"""Database configuration and lightweight compatibility migration."""
import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

SQLALCHEMY_DATABASE_URL = os.getenv("API_KEY_DATABASE_URL", "sqlite:///./api_keys.db")
connect_args = {"check_same_thread": False} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def ensure_schema() -> None:
    """Create tables and add non-destructive columns required by newer releases."""
    from . import models

    models.Base.metadata.create_all(bind=engine)
    if not SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
        return

    columns = {column["name"] for column in inspect(engine).get_columns("api_keys")}
    additions = {
        "scopes": "TEXT NOT NULL DEFAULT 'tasks:read'",
        "created_by": "VARCHAR",
        "revoked_at": "DATETIME",
    }
    with engine.begin() as connection:
        for name, declaration in additions.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE api_keys ADD COLUMN {name} {declaration}"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
