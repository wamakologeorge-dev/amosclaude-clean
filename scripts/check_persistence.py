"""Validate Amosclaud persistent storage before the web server starts."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path


def _is_hosted_production() -> bool:
    environment = os.getenv("ENVIRONMENT", os.getenv("APP_ENV", "")).strip().lower()
    return bool(
        environment in {"production", "prod"}
        or os.getenv("RAILWAY_ENVIRONMENT")
        or os.getenv("RENDER")
        or os.getenv("RENDER_SERVICE_ID")
    )


def _fail(message: str) -> None:
    print(f"[persistence] ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def _writable_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".amosclaud-write-test"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        _fail(f"Storage directory is not writable: {path} ({exc})")


def main() -> None:
    auth_db = Path(os.getenv("AUTH_DB_PATH", "data/auth.db")).expanduser()
    repository_root = Path(os.getenv("REPOSITORY_STORAGE_PATH", "data/repositories")).expanduser()
    hosted = _is_hosted_production()
    require_persistent = os.getenv("REQUIRE_PERSISTENT_STORAGE", "true" if hosted else "false").lower() == "true"

    if require_persistent:
        if not auth_db.is_absolute():
            _fail("AUTH_DB_PATH must be an absolute path on persistent storage in production")
        if not repository_root.is_absolute():
            _fail("REPOSITORY_STORAGE_PATH must be an absolute path on persistent storage in production")
        temporary_roots = (Path("/tmp"), Path("/var/tmp"))
        if any(auth_db == root or root in auth_db.parents for root in temporary_roots):
            _fail("AUTH_DB_PATH cannot use temporary storage in production")
        if any(repository_root == root or root in repository_root.parents for root in temporary_roots):
            _fail("REPOSITORY_STORAGE_PATH cannot use temporary storage in production")

    _writable_directory(auth_db.parent)
    _writable_directory(repository_root)

    try:
        with sqlite3.connect(auth_db) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS persistence_check (id INTEGER PRIMARY KEY, checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            db.commit()
    except sqlite3.Error as exc:
        _fail(f"Authentication database cannot be opened or written: {auth_db} ({exc})")

    print(f"[persistence] Authentication database: {auth_db}")
    print(f"[persistence] Repository storage: {repository_root}")
    print(f"[persistence] Persistent storage required: {require_persistent}")


if __name__ == "__main__":
    main()
