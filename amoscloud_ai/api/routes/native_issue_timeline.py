"""Persistent issue detail and Amosclaud Action timeline routes."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes import repositories, solo_development
from amoscloud_ai.models import AutonomousAgentRunRequest

router = APIRouter(prefix="/repositories", tags=["native-issue-timeline"])


class IssueActionRequest(BaseModel):
    """Start one governed Amosclaud Action from a native repository issue."""

    mode: Literal[
        "autonomous-check", "build", "fix", "deploy", "monitor"
    ] = "fix"
    branch: str = Field(default="main", min_length=1, max_length=200)
    instructions: str = Field(default="", max_length=20_000)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_activity_table(db: sqlite3.Connection) -> None:
    solo_development._ensure_tables(db)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS native_issue_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repository_id INTEGER NOT NULL,
            issue_id INTEGER NOT NULL,
            actor_id INTEGER,
            actor_kind TEXT NOT NULL CHECK(actor_kind IN ('user','amosclaud','system')),
            event_kind TEXT NOT NULL CHECK(event_kind IN ('comment','action','status')),
            body TEXT NOT NULL DEFAULT '',
            pipeline_id TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(repository_id) REFERENCES repositories(id) ON DELETE CASCADE,
            FOREIGN KEY(issue_id) REFERENCES native_issues(id) ON DELETE CASCADE,
            FOREIGN KEY(actor_id) REFERENCES users(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_native_issue_activity_issue
            ON native_issue_activity(repository_id, issue_id, id ASC);
        """
    )
    db.commit()


def _issue_row(
    db: sqlite3.Connection,
    repository_id: int,
    issue_id: int,
) -> sqlite3.Row:
    row = db.execute(
        "SELECT * FROM native_issues WHERE repository_id=? AND id=?",
        (repository_id, issue_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    return row


def _pipeline_snapshot(pipeline_id: str | None) -> dict[str, object] | None:
    if not pipeline_id:
        return None

    from amoscloud_ai.api.routes.pipelines import _get

    pipeline = _get(pipeline_id)
    if pipeline is None:
        return {
            "id": pipeline_id,
            "status": "unknown",
            "reply": "The linked Amosclaud Action record is not available yet.",
            "started_at": None,
            "finished_at": None,
        }
    return {
        "id": pipeline.id,
        "status": pipeline.status.value,
        "reply": pipeline.copilot_reply or pipeline.message,
        "started_at": pipeline.started_at.isoformat(),
        "finished_at": (
            pipeline.finished_at.isoformat() if pipeline.finished_at else None
        ),
    }


def _activity_dict(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": int(row["id"]),
        "actor_kind": str(row["actor_kind"]),
        "event_kind": str(row["event_kind"]),
        "body": str(row["body"]),
        "pipeline_id": str(row["pipeline_id"]) if row["pipeline_id"] else None,
        "pipeline": _pipeline_snapshot(row["pipeline_id"]),
        "created_at": str(row["created_at"]),
    }


def _issue_detail(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, object]:
    issue = solo_development._issue_dict(row)
    activity = db.execute(
        """SELECT * FROM native_issue_activity
           WHERE repository_id=? AND issue_id=? ORDER BY id ASC""",
        (row["repository_id"], row["id"]),
    ).fetchall()
    return {**issue, "activity": [_activity_dict(item) for item in activity]}


@router.get("/{repository_id}/issues/{issue_id}")
def get_issue_detail(
    repository_id: int,
    issue_id: int,
    user: sqlite3.Row = Depends(repositories._current_user),
) -> dict[str, object]:
    """Return the complete issue instructions and persistent Action timeline."""

    with repositories._db() as db:
        _ensure_activity_table(db)
        repositories._access(db, repository_id, int(user["id"]))
        return _issue_detail(db, _issue_row(db, repository_id, issue_id))


@router.post("/{repository_id}/issues/{issue_id}/actions", status_code=202)
async def run_issue_action(
    repository_id: int,
    issue_id: int,
    body: IssueActionRequest,
    request: Request,
    user: sqlite3.Row = Depends(repositories._current_user),
) -> dict[str, object]:
    """Queue Amosclaud work and attach its pipeline to the native issue."""

    branch = repositories._safe_branch(body.branch)
    with repositories._db() as db:
        _ensure_activity_table(db)
        access = repositories._access(db, repository_id, int(user["id"]))
        repositories._require_write(access)
        issue = _issue_row(db, repository_id, issue_id)
        issue_title = str(issue["title"]).strip()
        issue_body = str(issue["body"] or "").strip()

    sections = [
        f"Work on native Amosclaud issue #{issue_id}: {issue_title}",
        "Issue instructions:",
        issue_body or "No additional issue instructions were supplied.",
    ]
    if body.instructions.strip():
        sections.extend(["Operator follow-up:", body.instructions.strip()])
    objective = "\n\n".join(sections)

    from amoscloud_ai.api.routes.agent import run_agent

    result = await run_agent(
        AutonomousAgentRunRequest(
            mode=body.mode,
            objective=objective,
            branch=branch,
            metadata={
                "repository_id": repository_id,
                "issue_id": issue_id,
                "source": "native-platform-issue",
                "use_agent": True,
                "apply_changes": body.mode == "fix",
            },
        ),
        request,
    )

    with repositories._db() as db:
        _ensure_activity_table(db)
        _issue_row(db, repository_id, issue_id)
        db.execute(
            """INSERT INTO native_issue_activity(
                   repository_id,issue_id,actor_id,actor_kind,event_kind,
                   body,pipeline_id,created_at
               ) VALUES (?,?,?,'amosclaud','action',?,?,?)""",
            (
                repository_id,
                issue_id,
                int(user["id"]),
                result.reply or "Amosclaud Action queued.",
                result.pipeline_id,
                _now(),
            ),
        )
        db.execute(
            "UPDATE native_issues SET updated_at=? WHERE repository_id=? AND id=?",
            (_now(), repository_id, issue_id),
        )
        db.commit()
        refreshed = _issue_row(db, repository_id, issue_id)
        return _issue_detail(db, refreshed)
