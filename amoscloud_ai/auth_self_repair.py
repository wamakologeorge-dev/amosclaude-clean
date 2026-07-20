"""Protected self-repair for Amosclaud authentication infrastructure.

This service may create missing runtime folders, inspect the authentication
schema, back up the SQLite database, and verify cookie/database configuration.
It never deletes users, resets passwords, removes passkeys, or clears sessions.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_TABLES = {"users", "sessions"}
PROTECTED_TABLES = {"users", "sessions", "passkey_credentials", "mailboxes"}


@dataclass(frozen=True)
class AuthRepairResult:
    status: str
    changed: bool
    database: str
    backup: str | None
    checks: list[dict[str, Any]]
    actions: list[str]
    protections: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _database_path() -> Path:
    return Path(os.getenv("AUTH_DB_PATH", "/data/auth.db")).expanduser()


def _backup_database(path: Path) -> Path | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_dir / f"auth-{stamp}.db"
    shutil.copy2(path, backup)
    return backup


def _tables(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with sqlite3.connect(path) as db:
        rows = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(row[0]) for row in rows}


def diagnose_and_repair() -> AuthRepairResult:
    """Repair only non-destructive authentication infrastructure."""
    path = _database_path()
    actions: list[str] = []
    checks: list[dict[str, Any]] = []
    changed = False

    path.parent.mkdir(parents=True, exist_ok=True)
    checks.append({"name": "auth-directory", "passed": path.parent.is_dir(), "detail": str(path.parent)})

    backup = _backup_database(path)
    if backup:
        actions.append(f"Created protected database backup: {backup}")

    # Opening through the canonical auth connector creates missing schema while
    # preserving all existing rows via CREATE TABLE IF NOT EXISTS.
    from amoscloud_ai.api.routes.auth import _connect

    with _connect() as db:
        db.execute("PRAGMA integrity_check")
    if not path.exists():
        # DB_PATH may have been imported before AUTH_DB_PATH changed. Report this
        # clearly rather than touching another database.
        checks.append({"name": "canonical-database", "passed": False, "detail": "AUTH_DB_PATH differs from the loaded auth database path; restart required"})
    else:
        changed = backup is None
        checks.append({"name": "canonical-database", "passed": True, "detail": str(path)})

    tables = _tables(path)
    missing = sorted(REQUIRED_TABLES - tables)
    checks.append({"name": "required-schema", "passed": not missing, "detail": "ready" if not missing else f"missing: {', '.join(missing)}"})

    cookie_secure = os.getenv("AUTH_COOKIE_SECURE", "true").strip().lower() == "true"
    checks.append({"name": "secure-cookie", "passed": cookie_secure, "detail": "secure" if cookie_secure else "AUTH_COOKIE_SECURE is disabled"})

    persistent_hint = path.is_absolute() and str(path).startswith("/data/")
    checks.append({"name": "persistent-path", "passed": persistent_hint, "detail": str(path)})

    failed = [check for check in checks if not check["passed"]]
    status = "healthy" if not failed else "needs_configuration"
    if not failed:
        actions.append("Authentication infrastructure verified without modifying user records.")

    return AuthRepairResult(
        status=status,
        changed=changed,
        database=str(path),
        backup=str(backup) if backup else None,
        checks=checks,
        actions=actions,
        protections=[
            "Never delete or recreate the users table",
            "Never reset passwords or remove passkeys",
            "Never clear all sessions",
            "Never overwrite an existing authentication database",
            f"Protected tables: {', '.join(sorted(PROTECTED_TABLES))}",
        ],
    )
