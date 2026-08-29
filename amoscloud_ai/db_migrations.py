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
    Migration(
        3,
        "github_repository_sync_schema",
        "-- Applied by ensure_github_repository_schema.",
    ),
    Migration(
        4,
        "cloud_workspaces",
        """
        CREATE TABLE IF NOT EXISTS cloud_workspaces (
            id TEXT PRIMARY KEY,
            repository_id INTEGER NOT NULL UNIQUE,
            owner_id INTEGER NOT NULL,
            runtime_status TEXT NOT NULL DEFAULT 'not_started',
            runtime_detail TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_started_at TEXT,
            last_stopped_at TEXT,
            FOREIGN KEY(repository_id) REFERENCES repositories(id) ON DELETE CASCADE,
            FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_cloud_workspaces_owner
            ON cloud_workspaces(owner_id, updated_at);
        """,
    ),
    Migration(
        5,
        "native_actions",
        """
        CREATE TABLE IF NOT EXISTS native_action_runs (
            id TEXT PRIMARY KEY,
            repository_id INTEGER NOT NULL,
            pull_request_id INTEGER NOT NULL,
            head_sha TEXT NOT NULL,
            branch TEXT NOT NULL,
            requested_by INTEGER NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL CHECK(status IN ('pending','running','success','failed','cancelled')),
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            error_detail TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(repository_id) REFERENCES repositories(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_native_action_pr_history
            ON native_action_runs(repository_id, pull_request_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_native_action_recovery
            ON native_action_runs(status, created_at);
        """,
    ),
    Migration(
        6,
        "native_actions_queued_ref",
        """
        -- SQLite cannot extend an existing CHECK constraint. Rebuild the
        -- native Action table atomically while preserving legacy pending rows.
        BEGIN IMMEDIATE;
        CREATE TABLE native_action_runs_v6 (
            id TEXT PRIMARY KEY,
            repository_id INTEGER NOT NULL,
            pull_request_id INTEGER NOT NULL,
            head_sha TEXT NOT NULL,
            branch TEXT NOT NULL,
            requested_by INTEGER NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            action_ref TEXT,
            status TEXT NOT NULL CHECK(status IN ('pending','queued','running','success','failed','cancelled')),
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            error_detail TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(repository_id) REFERENCES repositories(id) ON DELETE CASCADE
        );
        INSERT INTO native_action_runs_v6(
            id,repository_id,pull_request_id,head_sha,branch,requested_by,
            reason,action_ref,status,created_at,started_at,finished_at,error_detail
        ) SELECT
            id,repository_id,pull_request_id,head_sha,branch,requested_by,
            reason,NULL,status,created_at,started_at,finished_at,error_detail
          FROM native_action_runs;
        DROP TABLE native_action_runs;
        ALTER TABLE native_action_runs_v6 RENAME TO native_action_runs;
        CREATE INDEX idx_native_action_pr_history
            ON native_action_runs(repository_id, pull_request_id, created_at DESC);
        CREATE INDEX idx_native_action_recovery
            ON native_action_runs(status, created_at);
        COMMIT;
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


def _create_github_connections(
    db: sqlite3.Connection,
    *,
    include_user_foreign_key: bool = True,
) -> None:
    foreign_key = (
        ",\n            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE"
        if include_user_foreign_key
        else ""
    )
    db.execute(f"""CREATE TABLE IF NOT EXISTS github_connections (
            user_id INTEGER PRIMARY KEY,
            github_user_id INTEGER,
            github_id TEXT,
            github_login TEXT NOT NULL,
            avatar_url TEXT,
            access_token_ciphertext TEXT NOT NULL,
            scopes TEXT NOT NULL DEFAULT '',
            connected_at TEXT NOT NULL,
            updated_at TEXT NOT NULL{foreign_key}
        )""")


def _ensure_github_connections_schema(db: sqlite3.Connection) -> None:
    """Accept both historical ``github_id`` and current ``github_user_id`` rows.

    Isolated synchronization databases may intentionally omit the account
    ``users`` table. Their connection table remains standalone and therefore
    must not acquire a foreign key to a table that does not exist.
    """

    users_table_exists = bool(
        db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
    )
    _create_github_connections(
        db,
        include_user_foreign_key=users_table_exists,
    )
    info = {row[1]: row for row in db.execute("PRAGMA table_info(github_connections)").fetchall()}
    if "github_user_id" not in info:
        db.execute("ALTER TABLE github_connections ADD COLUMN github_user_id INTEGER")
    if "github_id" not in info:
        db.execute("ALTER TABLE github_connections ADD COLUMN github_id TEXT")

    info = {row[1]: row for row in db.execute("PRAGMA table_info(github_connections)").fetchall()}
    table_empty = db.execute("SELECT 1 FROM github_connections LIMIT 1").fetchone() is None
    current_id = info.get("github_user_id")
    should_rebuild = bool(current_id and current_id[3] == 1 and (users_table_exists or table_empty))
    if should_rebuild:
        db.execute("ALTER TABLE github_connections RENAME TO github_connections_legacy")
        _create_github_connections(
            db,
            include_user_foreign_key=users_table_exists,
        )
        legacy = {
            row[1] for row in db.execute("PRAGMA table_info(github_connections_legacy)").fetchall()
        }
        if not table_empty:
            github_user_expr = (
                "github_user_id" if "github_user_id" in legacy else "CAST(github_id AS INTEGER)"
            )
            github_id_expr = (
                "github_id" if "github_id" in legacy else "CAST(github_user_id AS TEXT)"
            )
            db.execute(f"""INSERT INTO github_connections
                    (user_id,github_user_id,github_id,github_login,avatar_url,
                     access_token_ciphertext,scopes,connected_at,updated_at)
                    SELECT user_id,{github_user_expr},{github_id_expr},github_login,
                           avatar_url,access_token_ciphertext,scopes,connected_at,updated_at
                    FROM github_connections_legacy""")
        db.execute("DROP TABLE github_connections_legacy")

    db.execute("""UPDATE github_connections
           SET github_user_id=CAST(github_id AS INTEGER)
           WHERE github_user_id IS NULL
             AND github_id IS NOT NULL
             AND TRIM(github_id) <> ''""")
    db.execute("""UPDATE github_connections
           SET github_id=CAST(github_user_id AS TEXT)
           WHERE github_id IS NULL
             AND github_user_id IS NOT NULL""")


def ensure_github_repository_schema(db: sqlite3.Connection) -> None:
    """Idempotently add GitHub account and repository synchronization schema."""

    _ensure_github_connections_schema(db)
    columns = {row[1] for row in db.execute("PRAGMA table_info(repositories)").fetchall()}
    for name, sql_type in _GITHUB_REPOSITORY_COLUMNS.items():
        if name not in columns:
            db.execute(f"ALTER TABLE repositories ADD COLUMN {name} {sql_type}")
    db.execute("""CREATE INDEX IF NOT EXISTS idx_repositories_github_repository_id
           ON repositories(github_repository_id)""")
    db.execute("""CREATE INDEX IF NOT EXISTS idx_repositories_github_full_name
           ON repositories(github_full_name COLLATE NOCASE)""")


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
