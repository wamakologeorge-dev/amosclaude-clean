"""Private API endpoints that launch and report Amosclaud PR-agent work."""

from __future__ import annotations
from typing import Optional

import asyncio
import os
import secrets
import uuid
from datetime import datetime, timezone
from threading import Lock

from fastapi import APIRouter, Header, HTTPException

from amoscloud_ai.models import RepositoryTaskRequest, RepositoryTaskResponse, RepositoryTaskStatus
from amoscloud_ai.pr_agent import PullRequestAgent

router = APIRouter(prefix="/agent/tasks", tags=["pr-agent"])
_tasks: dict[str, RepositoryTaskResponse] = {}
_lock = Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
    result = await asyncio.to_thread(PullRequestAgent(task_id, request.objective, request.base_branch).execute)
    with _lock:
        current = _tasks[task_id]
        current.status = RepositoryTaskStatus.COMPLETED if result.status == "completed" else RepositoryTaskStatus.FAILED
        current.message = result.message
        current.pull_request_url = result.pull_request_url
        current.logs.extend(result.logs)
        current.updated_at = _now()


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
    asyncio.create_task(_perform_task(task_id, body))
    return task


def get_task_status(task_id: str) -> RepositoryTaskResponse:
    """Return a task snapshot for another trusted Amosclaud API route."""
    with _lock:
        task = _tasks.get(task_id)
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


@router.get("/{task_id}", response_model=RepositoryTaskResponse, summary="Get PR-agent task status")
async def get_task(task_id: str, x_amosclaud_owner_key: Optional[str] = Header(default=None)) -> RepositoryTaskResponse:
    _require_owner_key(x_amosclaud_owner_key)
    return get_task_status(task_id)
