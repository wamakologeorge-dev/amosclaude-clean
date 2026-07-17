"""Small, deterministic migration runner for the Amosclaud account database."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


MIGRATIONS = (
    Migration(
        1,
        "developer_webhooks",
        """
        CREATE TABLE IF NOT EXISTS developer_webhooks (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            events_json TEXT NOT NULL,
            secret_ciphertext TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            last_success_at TEXT,
            last_failure_at TEXT,
            failure_count INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_developer_webhooks_user
            ON developer_webhooks(user_id, status);
        CREATE TABLE IF NOT EXISTS webhook_deliveries (
            id TEXT PRIMARY KEY,
            webhook_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            response_code INTEGER,
            error TEXT,
            created_at TEXT NOT NULL,
            delivered_at TEXT,
            FOREIGN KEY(webhook_id) REFERENCES developer_webhooks(id) ON DELETE CASCADE
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_webhook_delivery_event
            ON webhook_deliveries(webhook_id, event_id);
        """,
    ),
)


def _checksum(migration: Migration) -> str:
    return hashlib.sha256(migration.sql.encode()).hexdigest()


def run_migrations(path: str | Path) -> list[int]:
    """Apply unapplied migrations atomically and reject edited history."""
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    applied: list[int] = []
    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )""")
        for migration in MIGRATIONS:
            existing = db.execute(
                "SELECT checksum FROM schema_migrations WHERE version=?",
                (migration.version,),
            ).fetchone()
            checksum = _checksum(migration)
            if existing:
                if existing[0] != checksum:
                    raise RuntimeError(
                        f"Migration {migration.version} checksum differs from applied history"
                    )
                continue
            with db:
                db.executescript(migration.sql)
                db.execute(
                    "INSERT INTO schema_migrations VALUES (?,?,?,?)",
                    (
                        migration.version,
                        migration.name,
                        checksum,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
            applied.append(migration.version)
    return applied
