"""Authenticated API bridge for sending the Amosclaud agent to GitHub and back."""

from __future__ import annotations

import os
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import get_user_from_session
from amoscloud_ai.api.routes.pr_tasks import _require_owner_key, get_task_status, list_recent_tasks, queue_task
from amoscloud_ai.models import RepositoryTaskRequest, RepositoryTaskResponse

router = APIRouter(prefix="/agent/github", tags=["github-agent-travel"])

DEFAULT_REPOSITORY = os.getenv(
    "AMOSCLAUD_AGENT_REPOSITORY",
    "wamakologeorge-dev/amosclaude-clean",
).strip()


class GitHubTravelRequest(BaseModel):
    repository: str = Field(default=DEFAULT_REPOSITORY, min_length=3, max_length=200)
    objective: str = Field(..., min_length=3, max_length=4000)
    base_branch: str = Field(default="main", min_length=1, max_length=200)
    action: Literal["inspect", "work", "work-and-open-pr"] = "work-and-open-pr"


class GitHubTravelResponse(BaseModel):
    accepted: bool
    task_id: str
    repository: str
    branch: str
    action: str
    stage: str
    message: str
    status_url: str


class ConnectionCheck(BaseModel):
    configured: bool
    reachable: bool
    detail: str


class GitHubTravelPreflightResponse(BaseModel):
    ready: bool
    repository: str
    github: ConnectionCheck
    model: ConnectionCheck


def _authorise(request: Request, owner_key: Optional[str]) -> None:
    """Allow a signed-in administrator or a valid owner key."""
    if owner_key:
        _require_owner_key(owner_key)
        return

    user = get_user_from_session(request.cookies.get("amos_session"))
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to Amosclaud before starting GitHub agent work.")
    if not bool(user["is_admin"]):
        raise HTTPException(status_code=403, detail="Administrator approval is required for repository changes.")


def _validate_repository(repository: str) -> str:
    value = repository.strip().strip("/")
    if value != DEFAULT_REPOSITORY:
        raise HTTPException(
            status_code=403,
            detail=(
                "This agent is currently restricted to the configured Amosclaud repository. "
                "Set AMOSCLAUD_AGENT_REPOSITORY to authorize another repository."
            ),
        )
    return value


async def _check_github(repository: str) -> ConnectionCheck:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        return ConnectionCheck(configured=False, reachable=False, detail="GITHUB_TOKEN is not configured.")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"https://api.github.com/repos/{repository}", headers=headers)
        if response.status_code == 200:
            permissions = response.json().get("permissions") or {}
            can_push = bool(permissions.get("push") or permissions.get("admin") or permissions.get("maintain"))
            detail = "Repository is reachable with push access." if can_push else "Repository is reachable, but push access was not confirmed."
            return ConnectionCheck(configured=True, reachable=can_push, detail=detail)
        if response.status_code in {401, 403}:
            return ConnectionCheck(configured=True, reachable=False, detail="GitHub rejected the configured token or its repository permissions.")
        if response.status_code == 404:
            return ConnectionCheck(configured=True, reachable=False, detail="Configured repository was not found or is not accessible to the token.")
        return ConnectionCheck(configured=True, reachable=False, detail=f"GitHub returned HTTP {response.status_code}.")
    except httpx.HTTPError:
        return ConnectionCheck(configured=True, reachable=False, detail="GitHub could not be reached from the Amosclaud service.")


async def _check_model() -> ConnectionCheck:
    model_url = os.getenv("AMOSCLAUD_MODEL_URL", "").strip().rstrip("/")
    if not model_url:
        return ConnectionCheck(configured=False, reachable=False, detail="AMOSCLAUD_MODEL_URL is not configured.")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{model_url}/api/tags")
        if response.status_code == 200:
            models = response.json().get("models") or []
            detail = f"Model service is reachable with {len(models)} installed model(s)."
            return ConnectionCheck(configured=True, reachable=True, detail=detail)
        return ConnectionCheck(configured=True, reachable=False, detail=f"Model service returned HTTP {response.status_code}.")
    except (httpx.HTTPError, ValueError):
        return ConnectionCheck(configured=True, reachable=False, detail="Model service could not be reached or returned an invalid response.")


@router.get("/preflight", response_model=GitHubTravelPreflightResponse)
async def github_travel_preflight(
    request: Request,
    x_amosclaud_owner_key: Optional[str] = Header(default=None),
) -> GitHubTravelPreflightResponse:
    """Verify production GitHub and model connectivity without exposing credentials."""
    _authorise(request, x_amosclaud_owner_key)
    github = await _check_github(DEFAULT_REPOSITORY)
    model = await _check_model()
    return GitHubTravelPreflightResponse(
        ready=github.reachable and model.reachable,
        repository=DEFAULT_REPOSITORY,
        github=github,
        model=model,
    )


@router.get("/history", response_model=list[RepositoryTaskResponse])
async def github_travel_history(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    x_amosclaud_owner_key: Optional[str] = Header(default=None),
) -> list[RepositoryTaskResponse]:
    """Return recent persisted GitHub travel and repository-agent task results."""
    _authorise(request, x_amosclaud_owner_key)
    return list_recent_tasks(limit)


@router.post("/travel", response_model=GitHubTravelResponse, status_code=202)
async def start_github_travel(
    body: GitHubTravelRequest,
    request: Request,
    x_amosclaud_owner_key: Optional[str] = Header(default=None),
) -> GitHubTravelResponse:
    """Queue isolated GitHub work and return a trackable travel task."""
    _authorise(request, x_amosclaud_owner_key)
    repository = _validate_repository(body.repository)

    objective = body.objective.strip()
    if body.action == "inspect":
        objective = (
            f"Inspect {repository} for this request and report findings. "
            "Do not change files unless a correction is strictly necessary: "
            f"{objective}"
        )
    elif body.action == "work":
        objective = (
            f"Work on {repository} in an isolated branch, validate the result, and leave it ready for review: "
            f"{objective}"
        )

    task = queue_task(RepositoryTaskRequest(objective=objective, base_branch=body.base_branch))
    return GitHubTravelResponse(
        accepted=True,
        task_id=task.task_id,
        repository=repository,
        branch=task.branch,
        action=body.action,
        stage="queued",
        message=task.message,
        status_url=f"/api/v1/agent/github/travel/{task.task_id}",
    )


@router.get("/travel/{task_id}", response_model=RepositoryTaskResponse)
async def github_travel_status(
    task_id: str,
    request: Request,
    x_amosclaud_owner_key: Optional[str] = Header(default=None),
) -> RepositoryTaskResponse:
    """Return the latest clone/edit/test/push/PR status for a travel task."""
    _authorise(request, x_amosclaud_owner_key)
    return get_task_status(task_id)
