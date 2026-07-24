"""Persistent native issue tracking for Amosclaud repositories."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from amoscloud_ai.api.routes import repositories


def _ensure_schema(db: sqlite3.Connection) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS repository_issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repository_id INTEGER NOT NULL,
            number INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','closed')),
            author_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(repository_id, number),
            FOREIGN KEY(repository_id) REFERENCES repositories(id) ON DELETE CASCADE,
            FOREIGN KEY(author_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_repository_issues_repo_state "
        "ON repository_issues(repository_id, state, number DESC)"
    )
    db.commit()


def _serialize(row: sqlite3.Row) -> dict:
    return {
        "id": int(row["id"]),
        "repository_id": int(row["repository_id"]),
        "number": int(row["number"]),
        "title": str(row["title"]),
        "description": str(row["description"]),
        "state": str(row["state"]),
        "author_id": int(row["author_id"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


class NativeIssueService:
    """Create and read issues after server-side repository permission checks."""

    def create(
        self,
        *,
        user,
        repository_id: int,
        title: str,
        description: str = "",
    ) -> dict:
        cleaned_title = " ".join(title.strip().split())
        if not cleaned_title:
            raise ValueError("Issue title is required")
        if len(cleaned_title) > 200:
            raise ValueError("Issue title must be 200 characters or fewer")
        cleaned_description = description.strip()[:20000]
        now = datetime.now(timezone.utc).isoformat()
        with repositories._db() as db:
            repository = repositories._access(db, repository_id, int(user["id"]))
            repositories._require_write(repository)
            _ensure_schema(db)
            next_number = int(
                db.execute(
                    "SELECT COALESCE(MAX(number), 0) + 1 FROM repository_issues WHERE repository_id=?",
                    (repository_id,),
                ).fetchone()[0]
            )
            cursor = db.execute(
                """INSERT INTO repository_issues(
                       repository_id,number,title,description,state,author_id,created_at,updated_at
                   ) VALUES (?,?,?,?, 'open', ?,?,?)""",
                (
                    repository_id,
                    next_number,
                    cleaned_title,
                    cleaned_description,
                    int(user["id"]),
                    now,
                    now,
                ),
            )
            db.execute(
                "UPDATE repositories SET updated_at=? WHERE id=?",
                (now, repository_id),
            )
            db.commit()
            row = db.execute(
                "SELECT * FROM repository_issues WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
        return _serialize(row)

    def list(self, *, user, repository_id: int, state: str | None = None) -> list[dict]:
        with repositories._db() as db:
            repositories._access(db, repository_id, int(user["id"]))
            _ensure_schema(db)
            if state in {"open", "closed"}:
                rows = db.execute(
                    "SELECT * FROM repository_issues WHERE repository_id=? AND state=? ORDER BY number DESC",
                    (repository_id, state),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM repository_issues WHERE repository_id=? ORDER BY number DESC",
                    (repository_id,),
                ).fetchall()
        return [_serialize(row) for row in rows]
