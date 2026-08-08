"""GitHub-native trigger bridge for the Amosclaud cooperation pipeline.

Pushes, pull requests, schedules, manual dispatches, repository dispatches, and
issue events enter the same durable pipeline used by web, agent, worker, node,
and legacy application surfaces. Automatic events never bypass write or deploy
approval gates.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes import auth
from amoscloud_ai.api.routes import pipeline_cooperation as cooperation

router = APIRouter(prefix="/github", tags=["github-native-triggers"])

PipelineMode = Literal["inspect", "build", "fix", "deploy", "monitor"]


class GitHubNativeEvent(BaseModel):
    delivery_id: str = Field(..., min_length=8, max_length=300)
    event: str = Field(..., min_length=1, max_length=100)
    action: str = Field(default="", max_length=100)
    repository: str = Field(..., min_length=3, max_length=300)
    ref: str = Field(default="", max_length=500)
    sha: str = Field(default="", max_length=100)
    actor: str = Field(default="", max_length=200)
    requested_mode: PipelineMode | None = None
    objective: str | None = Field(default=None, max_length=12_000)
    changed_files: list[str] = Field(default_factory=list, max_length=20_000)
    repository_scope: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)


def _expected_token() -> str:
    token = os.getenv("AMOSCLAUD_GITHUB_PIPELINE_TOKEN", "").strip()
    if not token:
        raise HTTPException(
            status_code=503,
            detail="GitHub-native pipeline token is not configured",
        )
    return token


def _provided_token(authorization: str | None, direct_token: str | None) -> str:
    if direct_token:
        return direct_token.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def _authenticate(authorization: str | None, direct_token: str | None) -> None:
    expected = _expected_token()
    provided = _provided_token(authorization, direct_token)
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid GitHub-native pipeline token")


def _automation_user() -> sqlite3.Row:
    configured_id = os.getenv("AMOSCLAUD_GITHUB_AUTOMATION_USER_ID", "").strip()
    configured_email = os.getenv("AMOSCLAUD_GITHUB_AUTOMATION_EMAIL", "").strip().lower()
    with auth._connect() as db:
        if configured_id:
            try:
                user_id = int(configured_id)
            except ValueError as exc:
                raise HTTPException(
                    status_code=503,
                    detail="AMOSCLAUD_GITHUB_AUTOMATION_USER_ID must be an integer",
                ) from exc
            user = db.execute(
                """SELECT id,name,email,is_admin,provider FROM users WHERE id=?""",
                (user_id,),
            ).fetchone()
        elif configured_email:
            user = db.execute(
                """SELECT id,name,email,is_admin,provider FROM users
                   WHERE lower(email)=?""",
                (configured_email,),
            ).fetchone()
        else:
            user = db.execute(
                """SELECT id,name,email,is_admin,provider FROM users
                   WHERE is_admin=1 ORDER BY id LIMIT 1"""
            ).fetchone()
    if not user:
        raise HTTPException(
            status_code=503,
            detail=(
                "No Amosclaud automation owner is available; configure "
                "AMOSCLAUD_GITHUB_AUTOMATION_USER_ID or "
                "AMOSCLAUD_GITHUB_AUTOMATION_EMAIL"
            ),
        )
    return user


def _ensure_table(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS cooperation_github_events (
            delivery_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            repository TEXT NOT NULL,
            event TEXT NOT NULL,
            action TEXT NOT NULL DEFAULT '',
            ref TEXT NOT NULL DEFAULT '',
            sha TEXT NOT NULL DEFAULT '',
            pipeline_id TEXT,
            status TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            error_detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(pipeline_id) REFERENCES cooperation_pipeline_runs(id)
                ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cooperation_github_events_repo
            ON cooperation_github_events(user_id,repository,created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_cooperation_github_events_pipeline
            ON cooperation_github_events(pipeline_id);
        """
    )


def _mode(body: GitHubNativeEvent) -> PipelineMode:
    if body.requested_mode:
        return body.requested_mode
    event = body.event.strip().lower()
    action = body.action.strip().lower()
    if event == "schedule":
        return "monitor"
    if event == "push":
        return "build"
    if event == "pull_request":
        return "build" if action in {"opened", "reopened", "synchronize", "ready_for_review"} else "inspect"
    if event == "repository_dispatch":
        for candidate in ("deploy", "fix", "build", "monitor", "inspect"):
            if candidate in action:
                return candidate  # type: ignore[return-value]
    if event == "workflow_dispatch":
        return "inspect"
    return "inspect"


def _branch(body: GitHubNativeEvent) -> str:
    branch = str(body.payload.get("head_ref") or body.payload.get("branch") or body.ref or "main")
    for prefix in ("refs/heads/", "refs/pull/"):
        if branch.startswith(prefix):
            branch = branch[len(prefix) :]
            break
    return branch[:200] or "main"


def _objective(body: GitHubNativeEvent, mode: PipelineMode) -> str:
    if body.objective and body.objective.strip():
        return body.objective.strip()
    action = f"/{body.action}" if body.action else ""
    scope = body.repository_scope.get("scope", "changed-files")
    return (
        f"Process GitHub {body.event}{action} for {body.repository} through the "
        f"shared Amosclaud {mode} pipeline. Include {scope}, legacy applications, "
        "GitHub-native applications, tests, security, evidence, and PipeFail results."
    )


def _payload_hash(body: GitHubNativeEvent) -> str:
    return hashlib.sha256(body.model_dump_json().encode()).hexdigest()


@router.post("/events", status_code=201)
def receive_github_event(
    body: GitHubNativeEvent,
    authorization: str | None = Header(default=None),
    x_amosclaud_github_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Create one deduplicated cooperation pipeline from a GitHub event."""

    _authenticate(authorization, x_amosclaud_github_token)
    user = _automation_user()
    user_id = int(user["id"])
    now = cooperation._now()
    digest = _payload_hash(body)

    with cooperation._LOCK, cooperation._db() as db:
        _ensure_table(db)
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT * FROM cooperation_github_events WHERE delivery_id=?",
            (body.delivery_id,),
        ).fetchone()
        if existing:
            if existing["pipeline_id"]:
                pipeline = cooperation._pipeline_row(
                    db,
                    existing["pipeline_id"],
                    user_id,
                    administrator=cooperation._is_admin(user),
                )
                db.commit()
                return {
                    "deduplicated": True,
                    "event": body.event,
                    "delivery_id": body.delivery_id,
                    "pipeline": cooperation._serialize_pipeline(db, pipeline),
                }
            db.commit()
            raise HTTPException(
                status_code=409,
                detail=f"GitHub event is already {existing['status']}",
            )
        db.execute(
            """INSERT INTO cooperation_github_events(
                delivery_id,user_id,repository,event,action,ref,sha,status,
                payload_hash,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,'processing',?,?,?)""",
            (
                body.delivery_id,
                user_id,
                body.repository,
                body.event,
                body.action,
                body.ref,
                body.sha,
                digest,
                now,
                now,
            ),
        )
        db.commit()

    mode = _mode(body)
    metadata = {
        "source": "github-native",
        "delivery_id": body.delivery_id,
        "github_event": body.event,
        "github_action": body.action,
        "github_repository": body.repository,
        "github_ref": body.ref,
        "github_sha": body.sha,
        "github_actor": body.actor,
        "changed_files": body.changed_files,
        "repository_scope": body.repository_scope,
        "github_payload": body.payload,
        "automatic_trigger": True,
        "write_approval_required": mode in {"fix", "deploy"},
    }
    try:
        pipeline = cooperation._create_pipeline(
            cooperation.CooperationPipelineCreate(
                objective=_objective(body, mode),
                mode=mode,
                project_id=f"github:{body.repository}"[:200],
                environment="production" if mode == "deploy" else "development",
                branch=_branch(body),
                allow_writes=False,
                metadata=metadata,
            ),
            user,
            repository_role="automation",
        )
    except Exception as exc:
        with cooperation._LOCK, cooperation._db() as db:
            _ensure_table(db)
            db.execute(
                """UPDATE cooperation_github_events SET status='failed',
                   error_detail=?,updated_at=? WHERE delivery_id=?""",
                (str(exc)[:20_000], cooperation._now(), body.delivery_id),
            )
            db.commit()
        raise

    with cooperation._LOCK, cooperation._db() as db:
        _ensure_table(db)
        db.execute(
            """UPDATE cooperation_github_events SET pipeline_id=?,status='created',
               updated_at=? WHERE delivery_id=?""",
            (pipeline["id"], cooperation._now(), body.delivery_id),
        )
        cooperation._event(
            db,
            pipeline_id=pipeline["id"],
            user_id=user_id,
            event_type="github.trigger.received",
            payload={
                "delivery_id": body.delivery_id,
                "event": body.event,
                "action": body.action,
                "repository": body.repository,
                "sha": body.sha,
                "changed_file_count": len(body.changed_files),
                "scope": body.repository_scope,
            },
        )
        db.commit()

    return {
        "deduplicated": False,
        "event": body.event,
        "delivery_id": body.delivery_id,
        "pipeline": pipeline,
    }


@router.get("/events/{delivery_id}")
def github_event_status(
    delivery_id: str,
    authorization: str | None = Header(default=None),
    x_amosclaud_github_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _authenticate(authorization, x_amosclaud_github_token)
    user = _automation_user()
    with cooperation._db() as db:
        _ensure_table(db)
        row = db.execute(
            """SELECT * FROM cooperation_github_events
               WHERE delivery_id=? AND user_id=?""",
            (delivery_id, int(user["id"])),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="GitHub event not found")
        return {
            "delivery_id": row["delivery_id"],
            "repository": row["repository"],
            "event": row["event"],
            "action": row["action"],
            "ref": row["ref"],
            "sha": row["sha"],
            "pipeline_id": row["pipeline_id"],
            "status": row["status"],
            "error_detail": row["error_detail"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
