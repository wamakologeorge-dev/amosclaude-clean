"""Workspace lifecycle for isolated Codespaces-style developer environments."""

from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai import workspace_provider
from amoscloud_ai.api.routes.auth import DB_PATH, get_user_from_session

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
DEFAULT_CPU = min(float(os.getenv("WORKSPACE_DEFAULT_CPU", "1")), 2.0)
DEFAULT_MEMORY_MB = min(int(os.getenv("WORKSPACE_DEFAULT_MEMORY_MB", "2048")), 4096)
DEFAULT_STORAGE_MB = int(os.getenv("WORKSPACE_DEFAULT_STORAGE_MB", "10240"))
DEFAULT_PIDS = min(int(os.getenv("WORKSPACE_DEFAULT_PIDS", "256")), 512)


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
            pids INTEGER NOT NULL DEFAULT 256,
            provider TEXT NOT NULL DEFAULT 'unassigned',
            provider_detail TEXT,
            editor_url TEXT,
            terminal_url TEXT,
            preview_url TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(repository_id) REFERENCES repositories(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    columns = {
        row[1] for row in db.execute("PRAGMA table_info(workspaces)").fetchall()
    }
    additions = {
        "pids": "INTEGER NOT NULL DEFAULT 256",
        "provider_detail": "TEXT",
        "terminal_url": "TEXT",
    }
    for name, sql_type in additions.items():
        if name not in columns:
            db.execute(f"ALTER TABLE workspaces ADD COLUMN {name} {sql_type}")
    member_columns = {
        row[1]
        for row in db.execute("PRAGMA table_info(organization_members)").fetchall()
    }
    if member_columns and "status" not in member_columns:
        db.execute(
            "ALTER TABLE organization_members "
            "ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"
        )
    db.commit()
    return db


def _current_user(amos_session: str | None = Cookie(default=None)) -> sqlite3.Row:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _repository_access(
    db: sqlite3.Connection,
    repository_id: int,
    user_id: int,
) -> sqlite3.Row:
    row = db.execute(
        """SELECT r.id,r.name,r.default_branch,
                  CASE WHEN r.owner_id=? THEN 'owner' ELSE COALESCE(c.role,om.role) END AS role
           FROM repositories r
           LEFT JOIN repository_collaborators c ON c.repository_id=r.id AND c.user_id=?
           LEFT JOIN organization_repositories ores ON ores.repository_id=r.id
           LEFT JOIN organization_members om ON om.organization_id=ores.organization_id
                AND om.user_id=? AND om.status='active'
           WHERE r.id=? AND (r.owner_id=? OR c.user_id=? OR om.user_id=?)""",
        (user_id, user_id, user_id, repository_id, user_id, user_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Repository not found")
    return row


def _workspace(
    db: sqlite3.Connection,
    workspace_id: str,
    user_id: int,
) -> sqlite3.Row:
    row = db.execute(
        "SELECT * FROM workspaces WHERE id=? AND user_id=?",
        (workspace_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return row


def _serialize(row: sqlite3.Row) -> dict:
    data = dict(row)
    running = data["status"] == "running"
    data["editor_available"] = running and bool(data.get("editor_url"))
    data["terminal_available"] = running and bool(data.get("terminal_url"))
    data["preview_available"] = running and bool(data.get("preview_url"))
    return data


def _update_runtime(
    workspace_id: str,
    user_id: int,
    *,
    status: str,
    provider: str | None = None,
    detail: str | None = None,
    editor_url: str | None = None,
    terminal_url: str | None = None,
    preview_url: str | None = None,
) -> dict:
    with _db() as db:
        _workspace(db, workspace_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            """UPDATE workspaces
               SET status=?,provider=COALESCE(?,provider),provider_detail=?,
                   editor_url=?,terminal_url=?,preview_url=?,updated_at=?
               WHERE id=? AND user_id=?""",
            (
                status,
                provider,
                detail,
                editor_url,
                terminal_url,
                preview_url,
                now,
                workspace_id,
                user_id,
            ),
        )
        db.commit()
        return _serialize(_workspace(db, workspace_id, user_id))


def _provider_payload(row: sqlite3.Row) -> dict:
    return {
        "workspace_id": str(row["id"]),
        "repository_id": int(row["repository_id"]),
        "cpu": min(float(row["cpu"]), 2.0),
        "memory_mb": min(int(row["memory_mb"]), 4096),
        "pids": min(int(row["pids"] or DEFAULT_PIDS), 512),
    }


def _apply_provider_result(
    workspace_id: str,
    user_id: int,
    result: dict,
) -> dict:
    return _update_runtime(
        workspace_id,
        user_id,
        status=str(result.get("status") or "failed"),
        provider=str(result.get("provider") or "workspace-worker"),
        detail=str(result.get("detail") or "") or None,
        editor_url=result.get("editor_url"),
        terminal_url=result.get("terminal_url"),
        preview_url=result.get("preview_url"),
    )


def _provider_failure(
    workspace_id: str,
    user_id: int,
    exc: workspace_provider.WorkspaceProviderError,
) -> None:
    _update_runtime(
        workspace_id,
        user_id,
        status="failed",
        provider="workspace-worker",
        detail=str(exc),
    )
    raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("", status_code=201)
def create_workspace(
    body: WorkspaceCreate,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    with _db() as db:
        repository = _repository_access(db, body.repository_id, user["id"])
        if repository["role"] == "viewer":
            raise HTTPException(
                status_code=403,
                detail="Developer access required to create a workspace",
            )
        existing = db.execute(
            """SELECT * FROM workspaces
               WHERE repository_id=? AND user_id=? AND status!='deleted'
               ORDER BY created_at DESC LIMIT 1""",
            (body.repository_id, user["id"]),
        ).fetchone()
        if existing:
            return _serialize(existing)

        workspace_id = "ws_" + secrets.token_urlsafe(12)
        now = datetime.now(timezone.utc).isoformat()
        large = body.machine == "large"
        cpu = min(DEFAULT_CPU * (2 if large else 1), 2.0)
        memory_mb = min(DEFAULT_MEMORY_MB * (2 if large else 1), 4096)
        storage_mb = DEFAULT_STORAGE_MB * (2 if large else 1)
        db.execute(
            """INSERT INTO workspaces(
                   id,repository_id,user_id,branch,status,machine,cpu,memory_mb,
                   storage_mb,pids,provider,created_at,updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,'unassigned',?,?)""",
            (
                workspace_id,
                body.repository_id,
                user["id"],
                body.branch or repository["default_branch"],
                "stopped",
                body.machine,
                cpu,
                memory_mb,
                storage_mb,
                DEFAULT_PIDS,
                now,
                now,
            ),
        )
        db.commit()
        return _serialize(_workspace(db, workspace_id, user["id"]))


@router.get("")
def list_workspaces(user: sqlite3.Row = Depends(_current_user)) -> list[dict]:
    with _db() as db:
        rows = db.execute(
            """SELECT * FROM workspaces
               WHERE user_id=? AND status!='deleted'
               ORDER BY updated_at DESC""",
            (user["id"],),
        ).fetchall()
    return [_serialize(row) for row in rows]


@router.get("/{workspace_id}")
def get_workspace(
    workspace_id: str,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    with _db() as db:
        return _serialize(_workspace(db, workspace_id, user["id"]))


@router.post("/{workspace_id}/start")
def start_workspace(
    workspace_id: str,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    with _db() as db:
        row = _workspace(db, workspace_id, user["id"])
        payload = _provider_payload(row)
    _update_runtime(
        workspace_id,
        user["id"],
        status="starting",
        provider="workspace-worker",
        detail="Provisioning isolated developer container",
    )
    try:
        provisioned = workspace_provider.provision_workspace(payload)
        if str(provisioned.get("status")) != "running":
            provisioned = workspace_provider.start_workspace(workspace_id)
        return _apply_provider_result(workspace_id, user["id"], provisioned)
    except workspace_provider.WorkspaceProviderError as exc:
        _provider_failure(workspace_id, user["id"], exc)


@router.post("/{workspace_id}/stop")
def stop_workspace(
    workspace_id: str,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    with _db() as db:
        row = _workspace(db, workspace_id, user["id"])
    if row["provider"] == "unassigned":
        return _update_runtime(
            workspace_id,
            user["id"],
            status="stopped",
            detail="Workspace has not been provisioned",
        )
    try:
        return _apply_provider_result(
            workspace_id,
            user["id"],
            workspace_provider.stop_workspace(workspace_id),
        )
    except workspace_provider.WorkspaceProviderError as exc:
        _provider_failure(workspace_id, user["id"], exc)


@router.post("/{workspace_id}/restart")
def restart_workspace(
    workspace_id: str,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    with _db() as db:
        row = _workspace(db, workspace_id, user["id"])
        payload = _provider_payload(row)
    _update_runtime(
        workspace_id,
        user["id"],
        status="starting",
        provider="workspace-worker",
        detail="Restarting isolated developer container",
    )
    try:
        if row["provider"] == "unassigned":
            workspace_provider.provision_workspace(payload)
            result = workspace_provider.start_workspace(workspace_id)
        else:
            result = workspace_provider.restart_workspace(workspace_id)
        return _apply_provider_result(workspace_id, user["id"], result)
    except workspace_provider.WorkspaceProviderError as exc:
        _provider_failure(workspace_id, user["id"], exc)


@router.delete("/{workspace_id}", status_code=204)
def delete_workspace(
    workspace_id: str,
    user: sqlite3.Row = Depends(_current_user),
) -> None:
    with _db() as db:
        row = _workspace(db, workspace_id, user["id"])
    if row["provider"] != "unassigned":
        try:
            workspace_provider.delete_workspace(workspace_id)
        except workspace_provider.WorkspaceProviderError as exc:
            _provider_failure(workspace_id, user["id"], exc)
    _update_runtime(
        workspace_id,
        user["id"],
        status="deleted",
        detail="Workspace container removed; repository storage preserved",
    )
