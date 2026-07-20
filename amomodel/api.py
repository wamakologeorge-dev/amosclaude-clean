"""Authenticated FastAPI operations for the AmoModel control plane."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import get_user_from_session

from .runtime import get_runtime

router = APIRouter(prefix="/amomodel", tags=["amomodel"])


class ExecuteRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=4000)
    wake: bool = True
    mode: Literal["plan", "build", "test", "review", "deploy", "monitor", "fix"] = "plan"
    repository_id: int | None = Field(default=None, ge=1)
    pull_request_id: int | None = Field(default=None, ge=1)
    target_file: str | None = Field(default=None, max_length=500)
    error_context: str | None = Field(default=None, max_length=20_000)
    commit_sha: str = Field(default="uncommitted", min_length=1, max_length=64)


def _user(request: Request) -> Any:
    user = get_user_from_session(request.cookies.get("amos_session"))
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to use AmoModel")
    return user


def _identity(user: Any) -> str:
    try:
        return str(user["email"] or user["name"] or "authenticated-user")
    except (KeyError, TypeError, IndexError):
        return "authenticated-user"


def _admin(request: Request) -> Any:
    user = _user(request)
    try:
        authorized = bool(user["is_admin"])
    except (KeyError, TypeError, IndexError):
        authorized = False
    if not authorized:
        raise HTTPException(status_code=403, detail="AmoModel lifecycle operations require an administrator")
    return user


@router.get("/status")
async def status(request: Request) -> dict[str, Any]:
    _user(request)
    return get_runtime().status()


@router.post("/power/on")
async def power_on(request: Request) -> dict[str, Any]:
    user = _admin(request)
    return get_runtime().power_on(_identity(user))


@router.post("/power/off")
async def power_off(request: Request) -> dict[str, Any]:
    user = _admin(request)
    return get_runtime().power_off(_identity(user))


@router.post("/restart")
async def restart(request: Request) -> dict[str, Any]:
    user = _admin(request)
    return get_runtime().restart(_identity(user))


@router.post("/execute")
async def execute(body: ExecuteRequest, request: Request) -> dict[str, Any]:
    user = _admin(request)
    try:
        return get_runtime().execute(
            _identity(user),
            body.objective,
            wake=body.wake,
            repository_id=body.repository_id,
            pull_request_id=body.pull_request_id,
            mode=body.mode,
            target_file=body.target_file,
            error_context=body.error_context,
            commit_sha=body.commit_sha,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/jobs/{task_id}")
async def job_status(task_id: str, request: Request) -> dict[str, Any]:
    _user(request)
    try:
        return get_runtime().job_status(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
