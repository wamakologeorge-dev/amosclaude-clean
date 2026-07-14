"""Human review threads for pipeline results and immediate Amosclaud repair runs."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import DB_PATH, get_user_from_session
from amoscloud_ai.api.routes.pipelines import _get, trigger_pipeline
from amoscloud_ai.models import PipelineTrigger

router = APIRouter(prefix="/reviews", tags=["reviews"])


class ReviewCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=5000)
    file_path: str | None = Field(default=None, max_length=500)
    line_number: int | None = Field(default=None, ge=1)
    kind: str = Field(default="comment", pattern="^(comment|solution|feedback|error|suggestion|approval)$")


class AgentFixRequest(BaseModel):
    instruction: str = Field(default="Diagnose and fix the blocking pipeline errors.", min_length=3, max_length=5000)
    file_path: str | None = Field(default=None, max_length=500)
    line_number: int | None = Field(default=None, ge=1)


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS pipeline_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pipeline_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            author_name TEXT NOT NULL,
            author_email TEXT NOT NULL,
            kind TEXT NOT NULL,
            body TEXT NOT NULL,
            file_path TEXT,
            line_number INTEGER,
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_pipeline_reviews_pipeline ON pipeline_reviews(pipeline_id, created_at);
        CREATE TABLE IF NOT EXISTS pipeline_fix_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_pipeline_id TEXT NOT NULL,
            repair_pipeline_id TEXT NOT NULL,
            requested_by INTEGER NOT NULL,
            instruction TEXT NOT NULL,
            file_path TEXT,
            line_number INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY(requested_by) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    db.commit()
    return db


def _user(amos_session: str | None = Cookie(default=None)):
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to review work")
    return user


@router.get("/{pipeline_id}")
def list_reviews(pipeline_id: str) -> list[dict]:
    if not _get(pipeline_id):
        raise HTTPException(status_code=404, detail="Pipeline not found")
    with _db() as db:
        rows = db.execute(
            """SELECT id,pipeline_id,author_name,kind,body,file_path,line_number,created_at,resolved_at
               FROM pipeline_reviews WHERE pipeline_id=? ORDER BY id ASC""",
            (pipeline_id,),
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("/{pipeline_id}", status_code=201)
def create_review(pipeline_id: str, body: ReviewCreate, user=Depends(_user)) -> dict:
    if not _get(pipeline_id):
        raise HTTPException(status_code=404, detail="Pipeline not found")
    now = datetime.now(timezone.utc).isoformat()
    with _db() as db:
        cursor = db.execute(
            """INSERT INTO pipeline_reviews(
                pipeline_id,user_id,author_name,author_email,kind,body,file_path,line_number,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                pipeline_id,
                user["id"],
                user["name"] or user["email"],
                user["email"],
                body.kind,
                body.body.strip(),
                body.file_path.strip() if body.file_path else None,
                body.line_number,
                now,
            ),
        )
        db.commit()
    return {
        "id": cursor.lastrowid,
        "pipeline_id": pipeline_id,
        "author_name": user["name"] or user["email"],
        "kind": body.kind,
        "body": body.body.strip(),
        "file_path": body.file_path,
        "line_number": body.line_number,
        "created_at": now,
        "resolved_at": None,
    }


@router.post("/{pipeline_id}/fix", status_code=202)
async def ask_agent_to_fix(pipeline_id: str, body: AgentFixRequest, user=Depends(_user)) -> dict:
    source = _get(pipeline_id)
    if not source:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    objective = body.instruction.strip()
    location = ""
    if body.file_path:
        location = f" Focus on {body.file_path}"
        if body.line_number:
            location += f" line {body.line_number}"
        location += "."

    repair = await trigger_pipeline(
        PipelineTrigger(
            trigger="autonomous",
            branch=source.branch,
            payload={
                "mode": "fix",
                "objective": f"{objective}{location}",
                "metadata": {
                    "source_pipeline_id": pipeline_id,
                    "requested_by": user["email"],
                    "file_path": body.file_path,
                    "line_number": body.line_number,
                },
            },
        )
    )

    now = datetime.now(timezone.utc).isoformat()
    with _db() as db:
        db.execute(
            """INSERT INTO pipeline_fix_requests(
                source_pipeline_id,repair_pipeline_id,requested_by,instruction,file_path,line_number,created_at
            ) VALUES (?,?,?,?,?,?,?)""",
            (pipeline_id, repair.id, user["id"], objective, body.file_path, body.line_number, now),
        )
        db.commit()

    return {
        "accepted": True,
        "source_pipeline_id": pipeline_id,
        "repair_pipeline_id": repair.id,
        "status": repair.status.value,
        "message": repair.copilot_reply or repair.message,
    }
