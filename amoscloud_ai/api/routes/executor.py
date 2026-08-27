"""Authenticated API for the Amosclaud-executor product."""

from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel, Field

from amosclaud_executor import ExecutorService, RepositoryTarget, SQLitePlanStore
from amoscloud_ai.api.routes.auth import DB_PATH, get_user_from_session
from amoscloud_ai.api.routes.github_repositories import (
    _connection,
)
from amoscloud_ai.api.routes.github_repositories import _db as github_db
from amoscloud_ai.api.routes.github_repositories import (
    _decrypt_token,
)
from amoscloud_ai.api.routes.repositories import REPOSITORY_ROOT

router = APIRouter(prefix="/executor", tags=["amosclaud-executor"])
service = ExecutorService(plan_store=SQLitePlanStore(DB_PATH))


class ExecutorPlanRequest(BaseModel):
    repository_id: int = Field(..., ge=1)
    objective: str = Field(..., min_length=1, max_length=8_000)
    source_branch: str | None = Field(default=None, max_length=200)


class ExecutorExecuteRequest(ExecutorPlanRequest):
    plan_id: str = Field(..., min_length=5, max_length=100)
    confirmation: str = Field(default="", max_length=32)
    delivery: Literal["branch", "pull_request"] = "pull_request"
    pull_request_title: str | None = Field(default=None, max_length=200)
    pull_request_body: str | None = Field(default=None, max_length=60_000)
    draft: bool = True


def _current_user(amos_session: str | None = Cookie(default=None)):
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to use Amosclaud-executor")
    return user


def _safe_repository_segment(repository_id: int) -> str:
    segment = str(int(repository_id))
    if not segment.isdigit():
        raise HTTPException(status_code=422, detail="Invalid repository id")
    return segment


def _owned_target(repository_id: int, user: sqlite3.Row) -> RepositoryTarget:
    with github_db() as db:
        row = db.execute(
            "SELECT * FROM repositories WHERE id=? AND owner_id=?",
            (repository_id, int(user["id"])),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Repository not found")

        repository_segment = _safe_repository_segment(repository_id)
        root = (REPOSITORY_ROOT / repository_segment).resolve()
        storage_root = REPOSITORY_ROOT.resolve()
        try:
            root.relative_to(storage_root)
        except ValueError as exc:
            raise HTTPException(
                status_code=500, detail="Repository storage boundary is invalid"
            ) from exc
        if not root.is_dir():
            raise HTTPException(
                status_code=409, detail="Repository workspace is unavailable; sync it first"
            )

        github_full_name = str(row["github_full_name"] or "").strip()
        token = None
        if github_full_name:
            connection = _connection(db, int(user["id"]))
            token = _decrypt_token(connection["access_token_ciphertext"])
        return RepositoryTarget(
            name=str(row["name"]),
            workspace=root,
            default_branch=str(row["github_default_branch"] or row["default_branch"] or "main"),
            github_full_name=github_full_name or None,
            github_token=token,
        )


@router.get("/capabilities")
def executor_capabilities(user=Depends(_current_user)) -> dict:
    del user
    return service.capabilities()


@router.post("/plan")
def create_executor_plan(
    body: ExecutorPlanRequest,
    user=Depends(_current_user),
) -> dict:
    target = _owned_target(body.repository_id, user)
    try:
        result = service.plan(
            target,
            body.objective,
            source_branch=body.source_branch,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.to_dict()


@router.post("/execute")
def execute_executor_plan(
    body: ExecutorExecuteRequest,
    user=Depends(_current_user),
) -> dict:
    target = _owned_target(body.repository_id, user)
    source_branch = body.source_branch or target.default_branch
    try:
        result = service.execute(
            target,
            body.objective,
            plan_id=body.plan_id,
            confirmation=body.confirmation,
            source_branch=source_branch,
            delivery=body.delivery,
            author_name=str(user["name"] or "Amosclaud"),
            author_email=str(user["email"] or "amosclaud@localhost"),
            pull_request_title=body.pull_request_title,
            pull_request_body=body.pull_request_body,
            draft=body.draft,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.to_dict()


__all__ = [
    "ExecutorExecuteRequest",
    "ExecutorPlanRequest",
    "create_executor_plan",
    "execute_executor_plan",
    "router",
    "service",
]
