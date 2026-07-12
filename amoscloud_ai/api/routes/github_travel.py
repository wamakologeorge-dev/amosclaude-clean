"""Authenticated API bridge for sending the Amosclaud agent to GitHub and back."""

from __future__ import annotations

import os
from typing import Literal, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import get_user_from_session
from amoscloud_ai.api.routes.pr_tasks import _require_owner_key, get_task, queue_task
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
    return await get_task(task_id, x_amosclaud_owner_key or os.getenv("AMOSCLAUD_OWNER_KEY"))
