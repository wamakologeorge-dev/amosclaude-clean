from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import get_user_from_session
from amoscloud_ai.core.workspace import WORKSPACE_DIRS, WorkspaceEngine, WorkspaceError

router = APIRouter(prefix="/local-workspace", tags=["local-workspace"])


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(default="", max_length=2_000_000)
    tags: list[str] = Field(default_factory=list, max_length=50)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    project: str | None = Field(default=None, max_length=120)
    assigned_to: str | None = Field(default=None, max_length=120)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=20_000)


def _current_user(amos_session: str | None = Cookie(default=None)) -> sqlite3.Row:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _engine() -> WorkspaceEngine:
    try:
        return WorkspaceEngine()
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _translate_error(exc: WorkspaceError) -> HTTPException:
    status = 404 if "not found" in str(exc).lower() else 400
    return HTTPException(status_code=status, detail=str(exc))


@router.get("")
def workspace_summary(user: sqlite3.Row = Depends(_current_user)) -> dict:
    del user
    return _engine().summary()


@router.get("/items")
def list_workspace_items(
    section: Literal[
        "projects", "notes", "tasks", "agents", "knowledge", "automations", "logs", "backups"
    ],
    user: sqlite3.Row = Depends(_current_user),
) -> list[dict]:
    del user
    try:
        return _engine().list_items(section)
    except WorkspaceError as exc:
        raise _translate_error(exc) from exc


@router.get("/item")
def read_workspace_item(
    path: str = Query(min_length=1, max_length=500),
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    del user
    try:
        return _engine().read_item(path)
    except (WorkspaceError, UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/notes", status_code=201)
def create_note(body: NoteCreate, user: sqlite3.Row = Depends(_current_user)) -> dict:
    try:
        engine = _engine()
        result = engine.create_note(body.title, body.content, body.tags)
        engine.append_activity({"action": "note.created", "path": result["path"], "user_id": user["id"]})
        return result
    except WorkspaceError as exc:
        raise _translate_error(exc) from exc


@router.post("/tasks", status_code=201)
def create_task(body: TaskCreate, user: sqlite3.Row = Depends(_current_user)) -> dict:
    try:
        engine = _engine()
        result = engine.create_task(body.title, body.project, body.assigned_to)
        engine.append_activity({"action": "task.created", "path": result["path"], "user_id": user["id"]})
        return result
    except WorkspaceError as exc:
        raise _translate_error(exc) from exc


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate, user: sqlite3.Row = Depends(_current_user)) -> dict:
    try:
        engine = _engine()
        result = engine.create_project(body.name, body.description)
        engine.append_activity({"action": "project.created", "path": result["path"], "user_id": user["id"]})
        return result
    except WorkspaceError as exc:
        raise _translate_error(exc) from exc


@router.get("/sections")
def workspace_sections(user: sqlite3.Row = Depends(_current_user)) -> dict:
    del user
    return {"sections": list(WORKSPACE_DIRS)}
