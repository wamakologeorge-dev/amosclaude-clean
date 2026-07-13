"""Private API endpoints that launch and report Amosclaud PR-agent work."""

from __future__ import annotations
from typing import Optional

import asyncio
import json
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

from fastapi import APIRouter, Header, HTTPException, Query

from amoscloud_ai.models import RepositoryTaskRequest, RepositoryTaskResponse, RepositoryTaskStatus
from amoscloud_ai.pr_agent import PullRequestAgent

router = APIRouter(prefix="/agent/tasks", tags=["pr-agent"])
_tasks: dict[str, RepositoryTaskResponse] = {}
_lock = Lock()


def _task_db_path() -> Path:
    configured = os.getenv("AGENT_TASK_DB_PATH", "").strip()
    if configured:
        return Path(configured)
    data_dir = Path(os.getenv("DATA_DIR", "data"))
    return data_dir / "agent_tasks.db"


def _task_db() -> sqlite3.Connection:
    path = _task_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS repository_agent_tasks (
            task_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            objective TEXT NOT NULL,
            branch TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            pull_request_url TEXT,
            logs_json TEXT NOT NULL
        )
        """
    )
    db.commit()
    return db


def _persist_task(task: RepositoryTaskResponse) -> None:
    with _task_db() as db:
        db.execute(
            """
            INSERT INTO repository_agent_tasks(
                task_id,status,objective,branch,message,created_at,updated_at,pull_request_url,logs_json
            ) VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(task_id) DO UPDATE SET
                status=excluded.status,
                objective=excluded.objective,
                branch=excluded.branch,
                message=excluded.message,
                updated_at=excluded.updated_at,
                pull_request_url=excluded.pull_request_url,
                logs_json=excluded.logs_json
            """,
            (
                task.task_id,
                task.status.value,
                task.objective,
                task.branch,
                task.message,
                task.created_at.isoformat(),
                task.updated_at.isoformat(),
                task.pull_request_url,
                json.dumps(task.logs),
            ),
        )
        db.commit()


def _task_from_row(row: sqlite3.Row) -> RepositoryTaskResponse:
    return RepositoryTaskResponse(
        task_id=row["task_id"],
        status=RepositoryTaskStatus(row["status"]),
        objective=row["objective"],
        branch=row["branch"],
        message=row["message"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        pull_request_url=row["pull_request_url"],
        logs=json.loads(row["logs_json"]),
    )


def _load_task(task_id: str) -> RepositoryTaskResponse | None:
    with _task_db() as db:
        row = db.execute(
            "SELECT * FROM repository_agent_tasks WHERE task_id=?",
            (task_id,),
        ).fetchone()
    return None if row is None else _task_from_row(row)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stale_after() -> timedelta:
    raw = os.getenv("AGENT_TASK_STALE_MINUTES", "60").strip()
    try:
        minutes = max(1, int(raw))
    except ValueError:
        minutes = 60
    return timedelta(minutes=minutes)


def _expire_if_stale(task: RepositoryTaskResponse) -> RepositoryTaskResponse:
    if task.status not in {RepositoryTaskStatus.QUEUED, RepositoryTaskStatus.RUNNING}:
        return task
    if _now() - task.updated_at <= _stale_after():
        return task

    task.status = RepositoryTaskStatus.FAILED
    task.message = (
        "Repository agent work was interrupted or stopped reporting progress. "
        "Start a new task after confirming the service is healthy."
    )
    task.updated_at = _now()
    task.logs.append("Task marked failed after exceeding the repository-agent stale timeout.")
    _persist_task(task)
    return task


def list_recent_tasks(limit: int = 20) -> list[RepositoryTaskResponse]:
    """Return newest persisted task snapshots after applying stale recovery."""
    safe_limit = min(max(limit, 1), 100)
    with _task_db() as db:
        rows = db.execute(
            "SELECT * FROM repository_agent_tasks ORDER BY created_at DESC LIMIT ?",
            (safe_limit,),
        ).fetchall()

    tasks: list[RepositoryTaskResponse] = []
    with _lock:
        for row in rows:
            task = _expire_if_stale(_task_from_row(row))
            _tasks[task.task_id] = task
            tasks.append(task)
    return tasks


def _require_owner_key(owner_key: Optional[str]) -> None:
    expected = os.environ.get("AMOSCLAUD_OWNER_KEY")
    if not expected:
        raise HTTPException(status_code=503, detail="PR agent is not configured: missing AMOSCLAUD_OWNER_KEY.")
    if not owner_key or not secrets.compare_digest(owner_key, expected):
        raise HTTPException(status_code=401, detail="A valid Amosclaud owner key is required.")


async def _perform_task(task_id: str, request: RepositoryTaskRequest) -> None:
    with _lock:
        current = _tasks[task_id]
        current.status = RepositoryTaskStatus.RUNNING
        current.updated_at = _now()
        current.logs.append("Repository agent started: reading instructions and preparing an isolated branch.")
        _persist_task(current)

    try:
        result = await asyncio.to_thread(PullRequestAgent(task_id, request.objective, request.base_branch).execute)
    except Exception as exc:
        with _lock:
            current = _tasks[task_id]
            current.status = RepositoryTaskStatus.FAILED
            current.message = "Repository agent stopped unexpectedly. Review the task logs and deployment logs."
            current.logs.append(f"Agent execution failed: {type(exc).__name__}")
            current.updated_at = _now()
            _persist_task(current)
        return

    with _lock:
        current = _tasks[task_id]
        current.status = RepositoryTaskStatus.COMPLETED if result.status == "completed" else RepositoryTaskStatus.FAILED
        current.message = result.message
        current.pull_request_url = result.pull_request_url
        current.logs.extend(result.logs)
        current.updated_at = _now()
        _persist_task(current)


def queue_task(body: RepositoryTaskRequest) -> RepositoryTaskResponse:
    """Queue isolated repository work after the caller has authenticated the owner."""
    task_id = str(uuid.uuid4())
    now = _now()
    task = RepositoryTaskResponse(
        task_id=task_id,
        status=RepositoryTaskStatus.QUEUED,
        objective=body.objective.strip(),
        branch=f"amosclaud/agent-{task_id[:8]}",
        message="Task accepted. Amosclaud is reading repository instructions and starting work on a pull-request branch.",
        created_at=now,
        updated_at=now,
        logs=["Task queued by authenticated owner."],
    )
    with _lock:
        _tasks[task_id] = task
        _persist_task(task)
    asyncio.create_task(_perform_task(task_id, body))
    return task


def get_task_status(task_id: str) -> RepositoryTaskResponse:
    """Return a task snapshot for another trusted Amosclaud API route."""
    with _lock:
        task = _tasks.get(task_id)
        if task is None:
            task = _load_task(task_id)
            if task is not None:
                _tasks[task_id] = task
        if task is not None:
            task = _expire_if_stale(task)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@router.post("", response_model=RepositoryTaskResponse, status_code=202, summary="Start autonomous PR work")
async def start_task(
    body: RepositoryTaskRequest,
    x_amosclaud_owner_key: Optional[str] = Header(default=None),
) -> RepositoryTaskResponse:
    """Accept an owner command and immediately begin repository work in the background."""
    _require_owner_key(x_amosclaud_owner_key)
    return queue_task(body)


@router.get("", response_model=list[RepositoryTaskResponse], summary="List recent PR-agent tasks")
async def recent_tasks(
    limit: int = Query(default=20, ge=1, le=100),
    x_amosclaud_owner_key: Optional[str] = Header(default=None),
) -> list[RepositoryTaskResponse]:
    _require_owner_key(x_amosclaud_owner_key)
    return list_recent_tasks(limit)


@router.get("/{task_id}", response_model=RepositoryTaskResponse, summary="Get PR-agent task status")
async def get_task(task_id: str, x_amosclaud_owner_key: Optional[str] = Header(default=None)) -> RepositoryTaskResponse:
    _require_owner_key(x_amosclaud_owner_key)
    return get_task_status(task_id)
