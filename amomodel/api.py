"""Authenticated FastAPI operations for the AmoModel runtime."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import get_user_from_session

from .runtime import get_runtime

router = APIRouter(prefix="/amomodel", tags=["amomodel"])


class ExecuteRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=4000)
    wake: bool = True


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
        return get_runtime().execute(_identity(user), body.objective, wake=body.wake)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
