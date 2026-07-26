from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[1]
ASYNC_SESSION = ROOT / "database" / "async_session.py"
ROOT_REQUIREMENTS = ROOT / "requirements.txt"
GATEWAY_REQUIREMENTS = ROOT / "api-gateway" / "requirements.txt"


def _load_async_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, url: str):
    monkeypatch.setenv("AMOSCLAUD_PLATFORM_DATABASE_URL", url)
    monkeypatch.setenv("AMOSCLAUD_DATA_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location(
        f"amosclaud_async_session_contract_{id(tmp_path)}", ASYNC_SESSION
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_async_database_drivers_are_declared() -> None:
    root = ROOT_REQUIREMENTS.read_text(encoding="utf-8")
    gateway = GATEWAY_REQUIREMENTS.read_text(encoding="utf-8")

    assert "aiosqlite>=0.20,<1" in root
    assert "asyncpg>=0.28,<1" in root
    assert "aiosqlite>=0.20,<1" in gateway
    assert "asyncpg>=0.28,<1" in gateway


def test_postgresql_url_uses_asyncpg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_async_session(
        monkeypatch,
        tmp_path,
        "postgresql+psycopg2://user:password@localhost/amosclaud",
    )

    assert (
        module._async_database_url()
        == "postgresql+asyncpg://user:password@localhost/amosclaud"
    )


@pytest.mark.asyncio
async def test_sqlite_async_session_executes_without_blocking_driver_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_async_session(monkeypatch, tmp_path, "sqlite:///:memory:")

    assert module._async_database_url() == "sqlite+aiosqlite:///:memory:"
    async with module.async_session_scope() as session:
        result = await session.execute(text("SELECT 1"))

    assert result.scalar_one() == 1
    await module._async_engine.dispose()
