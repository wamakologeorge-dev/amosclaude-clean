"""Authenticated control plane for Amosclaud's Daily Autonomous Builder."""

from __future__ import annotations

import sqlite3
import uuid
from typing import Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import _connect, get_user_from_session
from amoscloud_ai.autonomous_builder import (
    BACKLOG_STATUSES,
    ensure_autonomy_schema,
    ensure_settings,
    normalize_prefixes,
    run_daily_for_user,
    score_candidate,
    settings_dict,
)

router = APIRouter(prefix="/autonomy", tags=["daily-autonomous-builder"])


class AutonomySettingsUpdate(BaseModel):
    enabled: bool = False
    daily_limit: int = Field(default=1, ge=1, le=3)
    max_repair_attempts: int = Field(default=3, ge=1, le=3)
    allowed_repositories: list[str] = Field(default_factory=list, max_length=20)
    allowed_paths: list[str] = Field(default_factory=list, max_length=30)
    protected_paths: list[str] = Field(default_factory=list, max_length=50)
    staging_required: bool = True
    auto_merge: Literal[False] = False


class BacklogCreate(BaseModel):
    repository: str = Field(min_length=3, max_length=300)
    title: str = Field(min_length=3, max_length=200)
    objective: str = Field(min_length=10, max_length=10_000)
    source: str = Field(default="roadmap", min_length=2, max_length=100)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=20)
    user_value: int = Field(default=5, ge=0, le=10)
    roadmap_alignment: int = Field(default=5, ge=0, le=10)
    recurring_failure_reduction: int = Field(default=0, ge=0, le=10)
    maintainability_improvement: int = Field(default=0, ge=0, le=10)
    implementation_risk: int = Field(default=3, ge=0, le=10)
    security_risk: int = Field(default=1, ge=0, le=10)
    estimated_size: int = Field(default=3, ge=1, le=10)


class BacklogStatusUpdate(BaseModel):
    status: Literal["proposed", "rejected"]


def _current_user(amos_session: str | None = Cookie(default=None)) -> sqlite3.Row:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to manage autonomous building")
    return user


def _json(value) -> str:
    import json

    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _loads(value: str | None, fallback):
    import json

    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _clean_repository(value: str) -> str:
    repository = value.strip()
    if repository.count("/") != 1 or any(character.isspace() for character in repository):
        raise HTTPException(status_code=422, detail="Use a connected owner/repository name")
    return repository


def _require_imported_repository(db: sqlite3.Connection, user_id: int, repository: str) -> None:
    row = db.execute(
        """SELECT 1 FROM repositories
           WHERE owner_id=? AND github_full_name=? COLLATE NOCASE""",
        (user_id, repository),
    ).fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail="Import the connected GitHub repository before enabling autonomous work",
        )


def _backlog_dict(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["acceptance_criteria"] = _loads(item.pop("acceptance_criteria_json"), [])
    return item


def _run_dict(row: sqlite3.Row) -> dict:
    return dict(row)


@router.get("/settings")
def get_settings(user: sqlite3.Row = Depends(_current_user)) -> dict:
    with _connect() as db:
        row = ensure_settings(db, int(user["id"]))
    return settings_dict(row)


@router.put("/settings")
def update_settings(
    body: AutonomySettingsUpdate,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    repositories = sorted({_clean_repository(item) for item in body.allowed_repositories})
    allowed_paths = normalize_prefixes(body.allowed_paths)
    protected_paths = normalize_prefixes(body.protected_paths)
    if body.enabled and not repositories:
        raise HTTPException(
            status_code=422,
            detail="Allow at least one imported repository before enabling autonomy",
        )
    if body.enabled and not allowed_paths:
        raise HTTPException(
            status_code=422,
            detail="Allow at least one repository path before enabling autonomy",
        )

    now = _now()
    with _connect() as db:
        ensure_autonomy_schema(db, commit=False)
        ensure_settings(db, int(user["id"]), commit=False)
        for repository in repositories:
            _require_imported_repository(db, int(user["id"]), repository)
        db.execute(
            """UPDATE autonomy_settings SET
                   enabled=?,daily_limit=?,max_repair_attempts=?,
                   allowed_repositories_json=?,allowed_paths_json=?,
                   protected_paths_json=?,staging_required=?,auto_merge=0,updated_at=?
               WHERE user_id=?""",
            (
                int(body.enabled),
                body.daily_limit,
                body.max_repair_attempts,
                _json(repositories),
                _json(allowed_paths),
                _json(protected_paths),
                int(body.staging_required),
                now,
                user["id"],
            ),
        )
        db.commit()
        row = db.execute(
            "SELECT * FROM autonomy_settings WHERE user_id=?", (user["id"],)
        ).fetchone()
    return settings_dict(row)


@router.post("/backlog", status_code=201)
def create_backlog_item(
    body: BacklogCreate,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    repository = _clean_repository(body.repository)
    criteria = [" ".join(item.split()) for item in body.acceptance_criteria if item.strip()]
    if not criteria:
        raise HTTPException(status_code=422, detail="Add at least one acceptance criterion")
    item_id = "autoidea_" + uuid.uuid4().hex
    values = body.model_dump()
    values["repository"] = repository
    score = score_candidate(values)
    now = _now()
    with _connect() as db:
        ensure_autonomy_schema(db, commit=False)
        _require_imported_repository(db, int(user["id"]), repository)
        db.execute(
            """INSERT INTO autonomous_backlog(
                   id,user_id,repository,title,objective,source,
                   acceptance_criteria_json,user_value,roadmap_alignment,
                   recurring_failure_reduction,maintainability_improvement,
                   implementation_risk,security_risk,estimated_size,score,
                   status,created_at,updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                item_id,
                user["id"],
                repository,
                body.title.strip(),
                body.objective.strip(),
                body.source.strip(),
                _json(criteria),
                body.user_value,
                body.roadmap_alignment,
                body.recurring_failure_reduction,
                body.maintainability_improvement,
                body.implementation_risk,
                body.security_risk,
                body.estimated_size,
                score,
                "proposed",
                now,
                now,
            ),
        )
        db.commit()
        row = db.execute("SELECT * FROM autonomous_backlog WHERE id=?", (item_id,)).fetchone()
    return _backlog_dict(row)


@router.get("/backlog")
def list_backlog(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: sqlite3.Row = Depends(_current_user),
) -> list[dict]:
    if status is not None and status not in BACKLOG_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid backlog status")
    with _connect() as db:
        ensure_autonomy_schema(db)
        if status:
            rows = db.execute(
                """SELECT * FROM autonomous_backlog
                   WHERE user_id=? AND status=? ORDER BY score DESC,created_at LIMIT ?""",
                (user["id"], status, limit),
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT * FROM autonomous_backlog
                   WHERE user_id=? ORDER BY created_at DESC LIMIT ?""",
                (user["id"], limit),
            ).fetchall()
    return [_backlog_dict(row) for row in rows]


@router.patch("/backlog/{item_id}")
def update_backlog_status(
    item_id: str,
    body: BacklogStatusUpdate,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    with _connect() as db:
        ensure_autonomy_schema(db, commit=False)
        row = db.execute(
            "SELECT * FROM autonomous_backlog WHERE id=? AND user_id=?",
            (item_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Backlog item not found")
        if row["status"] in {"running", "completed"}:
            raise HTTPException(status_code=409, detail="Active or completed work cannot be reset")
        db.execute(
            "UPDATE autonomous_backlog SET status=?,updated_at=? WHERE id=?",
            (body.status, _now(), item_id),
        )
        db.commit()
        updated = db.execute("SELECT * FROM autonomous_backlog WHERE id=?", (item_id,)).fetchone()
    return _backlog_dict(updated)


@router.post("/run-now", status_code=202)
def run_now(user: sqlite3.Row = Depends(_current_user)) -> dict:
    return run_daily_for_user(int(user["id"]))


@router.get("/runs")
def list_runs(
    limit: int = Query(default=50, ge=1, le=200),
    user: sqlite3.Row = Depends(_current_user),
) -> list[dict]:
    with _connect() as db:
        ensure_autonomy_schema(db)
        rows = db.execute(
            """SELECT * FROM autonomous_runs
               WHERE user_id=? ORDER BY created_at DESC LIMIT ?""",
            (user["id"], limit),
        ).fetchall()
    return [_run_dict(row) for row in rows]


@router.get("/runs/{run_id}")
def get_run(run_id: str, user: sqlite3.Row = Depends(_current_user)) -> dict:
    with _connect() as db:
        ensure_autonomy_schema(db)
        row = db.execute(
            "SELECT * FROM autonomous_runs WHERE id=? AND user_id=?",
            (run_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Autonomous run not found")
        events = db.execute(
            """SELECT event_type,message,details_json,created_at
               FROM autonomous_run_events WHERE run_id=? ORDER BY id""",
            (run_id,),
        ).fetchall()
    result = _run_dict(row)
    result["events"] = [
        {
            "event_type": event["event_type"],
            "message": event["message"],
            "details": _loads(event["details_json"], {}),
            "created_at": event["created_at"],
        }
        for event in events
    ]
    return result
