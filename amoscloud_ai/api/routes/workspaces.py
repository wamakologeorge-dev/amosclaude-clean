"""Workspace lifecycle metadata for Codespaces-style developer environments."""

from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import DB_PATH, get_user_from_session

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
DEFAULT_CPU = float(os.getenv("WORKSPACE_DEFAULT_CPU", "1"))
DEFAULT_MEMORY_MB = int(os.getenv("WORKSPACE_DEFAULT_MEMORY_MB", "2048"))
DEFAULT_STORAGE_MB = int(os.getenv("WORKSPACE_DEFAULT_STORAGE_MB", "10240"))


class WorkspaceCreate(BaseModel):
    repository_id: int
    branch: str = Field(default="main", min_length=1, max_length=200)
    machine: Literal["standard", "large"] = "standard"


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS workspaces (
            id TEXT PRIMARY KEY,
            repository_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            branch TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('starting','running','stopped','failed','deleted')),
            machine TEXT NOT NULL,
            cpu REAL NOT NULL,
            memory_mb INTEGER NOT NULL,
            storage_mb INTEGER NOT NULL,
            provider TEXT NOT NULL DEFAULT 'unassigned',
            editor_url TEXT,
            preview_url TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(repository_id) REFERENCES repositories(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    db.commit()
    return db


def _current_user(amos_session: str | None = Cookie(default=None)) -> sqlite3.Row:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _repository_access(db: sqlite3.Connection, repository_id: int, user_id: int) -> sqlite3.Row:
    row = db.execute(
        """SELECT r.id,r.name,r.default_branch,
                  CASE WHEN r.owner_id=? THEN 'owner' ELSE c.role END AS role
           FROM repositories r
           LEFT JOIN repository_collaborators c ON c.repository_id=r.id AND c.user_id=?
           LEFT JOIN organization_repositories ores ON ores.repository_id=r.id
           LEFT JOIN organization_members om ON om.organization_id=ores.organization_id AND om.user_id=?
           WHERE r.id=? AND (r.owner_id=? OR c.user_id=? OR om.user_id=?)""",
        (user_id, user_id, user_id, repository_id, user_id, user_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Repository not found")
    return row


def _workspace(db: sqlite3.Connection, workspace_id: str, user_id: int) -> sqlite3.Row:
    row = db.execute("SELECT * FROM workspaces WHERE id=? AND user_id=?", (workspace_id, user_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return row


def _serialize(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["terminal_available"] = data["status"] == "running" and bool(data["editor_url"])
    data["preview_available"] = data["status"] == "running" and bool(data["preview_url"])
    return data


@router.post("", status_code=201)
def create_workspace(body: WorkspaceCreate, user: sqlite3.Row = Depends(_current_user)) -> dict:
    with _db() as db:
        repository = _repository_access(db, body.repository_id, user["id"])
        if repository["role"] == "viewer":
            raise HTTPException(status_code=403, detail="Developer access required to create a workspace")
        existing = db.execute(
            "SELECT * FROM workspaces WHERE repository_id=? AND user_id=? AND status!='deleted' ORDER BY created_at DESC LIMIT 1",
            (body.repository_id, user["id"]),
        ).fetchone()
        if existing:
            return _serialize(existing)

        workspace_id = "ws_" + secrets.token_urlsafe(12)
        now = datetime.now(timezone.utc).isoformat()
        large = body.machine == "large"
        db.execute(
            """INSERT INTO workspaces(id,repository_id,user_id,branch,status,machine,cpu,memory_mb,storage_mb,provider,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,'unassigned',?,?)""",
            (
                workspace_id,
                body.repository_id,
                user["id"],
                body.branch or repository["default_branch"],
                "stopped",
                body.machine,
                DEFAULT_CPU * (2 if large else 1),
                DEFAULT_MEMORY_MB * (2 if large else 1),
                DEFAULT_STORAGE_MB * (2 if large else 1),
                now,
                now,
            ),
        )
        db.commit()
        return _serialize(_workspace(db, workspace_id, user["id"]))


@router.get("")
def list_workspaces(user: sqlite3.Row = Depends(_current_user)) -> list[dict]:
    with _db() as db:
        rows = db.execute("SELECT * FROM workspaces WHERE user_id=? AND status!='deleted' ORDER BY updated_at DESC", (user["id"],)).fetchall()
    return [_serialize(row) for row in rows]


def _set_status(workspace_id: str, user_id: int, status: str) -> dict:
    with _db() as db:
        _workspace(db, workspace_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        db.execute("UPDATE workspaces SET status=?,updated_at=? WHERE id=?", (status, now, workspace_id))
        db.commit()
        return _serialize(_workspace(db, workspace_id, user_id))


@router.post("/{workspace_id}/start")
def start_workspace(workspace_id: str, user: sqlite3.Row = Depends(_current_user)) -> dict:
    workspace = _set_status(workspace_id, user["id"], "starting")
    workspace["message"] = "Workspace provisioning is queued. A container provider must be connected before terminal and preview URLs become available."
    return workspace


@router.post("/{workspace_id}/stop")
def stop_workspace(workspace_id: str, user: sqlite3.Row = Depends(_current_user)) -> dict:
    return _set_status(workspace_id, user["id"], "stopped")


@router.post("/{workspace_id}/restart")
def restart_workspace(workspace_id: str, user: sqlite3.Row = Depends(_current_user)) -> dict:
    return _set_status(workspace_id, user["id"], "starting")


@router.delete("/{workspace_id}", status_code=204)
def delete_workspace(workspace_id: str, user: sqlite3.Row = Depends(_current_user)) -> None:
    _set_status(workspace_id, user["id"], "deleted")
