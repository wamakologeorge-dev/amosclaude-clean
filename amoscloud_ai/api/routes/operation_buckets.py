"""Per-user operation buckets for repositories, jobs, events, and verified results."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query

from amoscloud_ai.api.routes.auth import _connect, get_user_from_session

router = APIRouter(prefix="/operations", tags=["operation-buckets"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def ensure_bucket_schema(db: sqlite3.Connection, *, commit: bool = True) -> None:
    """Create the tenant boundary and extend existing task records safely."""
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS operation_buckets (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_operation_buckets_user
            ON operation_buckets(user_id);
        """
    )
    has_tasks = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='global_tasks'"
    ).fetchone()
    if has_tasks:
        columns = {
            row[1] for row in db.execute("PRAGMA table_info(global_tasks)").fetchall()
        }
        if "bucket_id" not in columns:
            db.execute("ALTER TABLE global_tasks ADD COLUMN bucket_id TEXT")
        if "verification_id" not in columns:
            db.execute("ALTER TABLE global_tasks ADD COLUMN verification_id TEXT")
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_global_tasks_bucket_created
            ON global_tasks(bucket_id, created_at DESC)
            """
        )
    if commit:
        db.commit()


def ensure_user_bucket(
    db: sqlite3.Connection, user_id: int, *, commit: bool = True
) -> sqlite3.Row:
    """Return the one durable operation bucket owned by a user."""
    ensure_bucket_schema(db, commit=commit)
    row = db.execute(
        "SELECT * FROM operation_buckets WHERE user_id=?", (user_id,)
    ).fetchone()
    if not row:
        bucket_id = "bucket_" + uuid.uuid4().hex
        now = _now()
        db.execute(
            """
            INSERT OR IGNORE INTO operation_buckets(
                id,user_id,status,created_at,updated_at
            )
            VALUES (?,?,'active',?,?)
            """,
            (bucket_id, user_id, now, now),
        )
        row = db.execute(
            "SELECT * FROM operation_buckets WHERE user_id=?", (user_id,)
        ).fetchone()
    if not row:
        raise RuntimeError("Unable to provision the user's operation bucket")
    if _table_exists(db, "global_tasks"):
        db.execute(
            """
            UPDATE global_tasks SET bucket_id=?
            WHERE user_id=? AND bucket_id IS NULL
            """,
            (row["id"], user_id),
        )
    if commit:
        db.commit()
    return row


def assign_task_bucket(
    db: sqlite3.Connection, task_id: str, user_id: int
) -> str:
    """Attach a task to its owner's bucket and return the bucket ID."""
    bucket = ensure_user_bucket(db, user_id)
    db.execute(
        "UPDATE global_tasks SET bucket_id=? WHERE id=? AND user_id=?",
        (bucket["id"], task_id, user_id),
    )
    db.execute(
        "UPDATE operation_buckets SET updated_at=? WHERE id=?",
        (_now(), bucket["id"]),
    )
    return str(bucket["id"])


def _current_user(
    amos_session: str | None = Cookie(default=None),
) -> sqlite3.Row:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to access your operation bucket")
    return user


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    return bool(
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
    )


def _task(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["require_approval"] = bool(item.get("require_approval"))
    item["metadata"] = _loads(item.pop("metadata_json", None), {})
    item["artifacts"] = _loads(item.pop("artifacts_json", None), [])
    return item


@router.get("/bucket")
def get_operation_bucket(
    limit: int = Query(default=25, ge=1, le=100),
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    """Return the signed-in user's repositories, operations, and result counts."""
    with _connect() as db:
        from amoscloud_ai.api.routes.task_router import _ensure_schema

        _ensure_schema(db)
        bucket = ensure_user_bucket(db, int(user["id"]))
        tasks = db.execute(
            """
            SELECT * FROM global_tasks
            WHERE user_id=? AND bucket_id=?
            ORDER BY created_at DESC LIMIT ?
            """,
            (user["id"], bucket["id"], limit),
        ).fetchall()
        repositories: list[dict[str, Any]] = []
        repository_count = 0
        if _table_exists(db, "repositories"):
            repository_count = int(
                db.execute(
                    "SELECT COUNT(*) FROM repositories WHERE owner_id=?",
                    (user["id"],),
                ).fetchone()[0]
            )
            repository_columns = {
                row[1] for row in db.execute("PRAGMA table_info(repositories)").fetchall()
            }
            github_full_name = (
                "github_full_name"
                if "github_full_name" in repository_columns
                else "NULL AS github_full_name"
            )
            github_html_url = (
                "github_html_url"
                if "github_html_url" in repository_columns
                else "NULL AS github_html_url"
            )
            repositories = [
                dict(row)
                for row in db.execute(
                    f"""
                    SELECT id,name,description,visibility,default_branch,
                           {github_full_name},{github_html_url},created_at,updated_at
                    FROM repositories WHERE owner_id=?
                    ORDER BY updated_at DESC LIMIT ?
                    """,
                    (user["id"], limit),
                ).fetchall()
            ]
        counts = {
            "repositories": repository_count,
            "operations": db.execute(
                "SELECT COUNT(*) FROM global_tasks WHERE bucket_id=?",
                (bucket["id"],),
            ).fetchone()[0],
            "active": db.execute(
                """
                SELECT COUNT(*) FROM global_tasks
                WHERE bucket_id=? AND status IN ('queued','awaiting_approval','running')
                """,
                (bucket["id"],),
            ).fetchone()[0],
            "verified_results": db.execute(
                """
                SELECT COUNT(*) FROM global_tasks
                WHERE bucket_id=? AND status='completed'
                  AND verification_id IS NOT NULL
                """,
                (bucket["id"],),
            ).fetchone()[0],
        }
    return {
        "id": bucket["id"],
        "status": bucket["status"],
        "owner": {"id": user["id"], "name": user["name"]},
        "created_at": bucket["created_at"],
        "updated_at": bucket["updated_at"],
        "counts": counts,
        "repositories": repositories,
        "operations": [_task(row) for row in tasks],
    }


@router.get("/bucket/events")
def get_operation_bucket_events(
    limit: int = Query(default=100, ge=1, le=500),
    user: sqlite3.Row = Depends(_current_user),
) -> list[dict[str, Any]]:
    """Return the ordered operation ledger for the signed-in user's bucket."""
    with _connect() as db:
        from amoscloud_ai.api.routes.task_router import _ensure_schema

        _ensure_schema(db)
        bucket = ensure_user_bucket(db, int(user["id"]))
        rows = db.execute(
            """
            SELECT e.task_id,e.event_type,e.message,e.details_json,e.created_at
            FROM global_task_events e
            JOIN global_tasks t ON t.id=e.task_id
            WHERE t.bucket_id=?
            ORDER BY e.id DESC LIMIT ?
            """,
            (bucket["id"], limit),
        ).fetchall()
    return [
        {
            "task_id": row["task_id"],
            "event_type": row["event_type"],
            "message": row["message"],
            "details": _loads(row["details_json"], {}),
            "created_at": row["created_at"],
        }
        for row in rows
    ]
