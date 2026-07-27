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
    Migration(
        2,
        "native_repository_base_schema",
        """
        CREATE TABLE IF NOT EXISTS repositories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            name TEXT NOT NULL COLLATE NOCASE,
            description TEXT NOT NULL DEFAULT '',
            visibility TEXT NOT NULL DEFAULT 'private',
            default_branch TEXT NOT NULL DEFAULT 'main',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(owner_id, name),
            FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_repositories_owner
            ON repositories(owner_id, updated_at);
        CREATE TABLE IF NOT EXISTS repository_collaborators (
            repository_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('developer','viewer')),
            created_at TEXT NOT NULL,
            PRIMARY KEY(repository_id, user_id),
            FOREIGN KEY(repository_id) REFERENCES repositories(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_repository_collaborators_user
            ON repository_collaborators(user_id, repository_id);
        """,
    ),
)

_GITHUB_REPOSITORY_COLUMNS = {
    "github_full_name": "TEXT",
    "github_html_url": "TEXT",
    "github_default_branch": "TEXT",
    "github_last_sync_at": "TEXT",
    "github_last_sync_attempt_at": "TEXT",
    "github_sync_state": "TEXT",
    "github_sync_detail": "TEXT",
    "github_last_remote_sha": "TEXT",
    "github_repository_id": "INTEGER",
}


def _checksum(migration: Migration) -> str:
    return hashlib.sha256(migration.sql.encode()).hexdigest()


def ensure_github_repository_schema(db: sqlite3.Connection) -> None:
    """Idempotently add GitHub account and repository synchronization schema.

    Production calls this from migration 3 before traffic. Tests and legacy CLI
    entry points may also call it after creating an isolated base schema.
    """

    db.execute(
        """CREATE TABLE IF NOT EXISTS github_connections (
            user_id INTEGER PRIMARY KEY,
            github_user_id INTEGER NOT NULL,
            github_login TEXT NOT NULL,
            avatar_url TEXT,
            access_token_ciphertext TEXT NOT NULL,
            scopes TEXT NOT NULL DEFAULT '',
            connected_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )"""
    )
    columns = {
        row[1] for row in db.execute("PRAGMA table_info(repositories)").fetchall()
    }
    for name, sql_type in _GITHUB_REPOSITORY_COLUMNS.items():
        if name not in columns:
            db.execute(f"ALTER TABLE repositories ADD COLUMN {name} {sql_type}")
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_repositories_github_repository_id
           ON repositories(github_repository_id)"""
    )
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_repositories_github_full_name
           ON repositories(github_full_name COLLATE NOCASE)"""
    )


def run_migrations(path: str | Path) -> list[int]:
    """Apply unapplied migrations atomically and reject edited history."""

    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    applied: list[int] = []
    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )"""
        )
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
                if migration.version == 3:
                    ensure_github_repository_schema(db)
                else:
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
