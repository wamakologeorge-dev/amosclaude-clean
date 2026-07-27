"""Authenticated control-plane routes for isolated Amosclaud workspaces."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response

from amoscloud_ai import workspace_runtime
from amoscloud_ai.api.routes.repositories import (
    _access,
    _current_user,
    _db,
    _require_owner,
    _require_write,
)

router = APIRouter(prefix="/cloud-workspaces", tags=["cloud-workspaces"])


def _repository(repository_id: int, user_id: int) -> sqlite3.Row:
    with _db() as db:
        return _access(db, repository_id, user_id)


def _workspace(repository_id: int, user: sqlite3.Row) -> dict:
    repository = _repository(repository_id, int(user["id"]))
    _require_write(repository)
    return workspace_runtime.workspace_for_repository(
        int(repository["id"]), int(repository["owner_id"])
    )


@router.get("/runtime")
def runtime_status(user: sqlite3.Row = Depends(_current_user)) -> dict:
    del user
    return workspace_runtime.runtime_health()


@router.get("/repositories/{repository_id}")
def repository_workspace_status(
    repository_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    workspace = _workspace(repository_id, user)
    payload = {
        "workspace": workspace,
        "runtime": workspace_runtime.runtime_health(),
        "persistent_repository": True,
    }
    if workspace_runtime.configured() and workspace["runtime_status"] != "not_started":
        try:
            payload["container"] = workspace_runtime.remote_status(workspace)
        except RuntimeError:
            payload["container_error"] = "Unable to retrieve container status."
    return payload


@router.post("/repositories/{repository_id}/start")
def start_repository_workspace(
    repository_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    workspace = _workspace(repository_id, user)
    if not workspace_runtime.configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "The isolated workspace runtime is not configured. Set "
                "AMOSCLAUD_WORKSPACE_RUNTIME_URL and AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN."
            ),
        )
    try:
        container = workspace_runtime.start_workspace(
            workspace,
            environment={
                "AMOSCLAUD_PROJECT_REPOSITORY_ID": str(repository_id),
                "AMOSCLAUD_PROJECT_OWNER_ID": str(workspace["owner_id"]),
            },
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Workspace runtime is currently unavailable.") from exc
    return {"workspace": workspace, "container": container}


@router.post("/repositories/{repository_id}/stop")
def stop_repository_workspace(
    repository_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    workspace = _workspace(repository_id, user)
    try:
        container = workspace_runtime.stop_workspace(workspace)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Workspace runtime is currently unavailable.") from exc
    return {"workspace": workspace, "container": container}


@router.post("/repositories/{repository_id}/terminal-ticket")
def create_terminal_ticket(
    repository_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    workspace = _workspace(repository_id, user)
    if not workspace_runtime.configured():
        raise HTTPException(status_code=503, detail="Workspace runtime is not configured")
    try:
        container = workspace_runtime.remote_status(workspace)
        if not container.get("running"):
            raise HTTPException(status_code=409, detail="Start the workspace first")
        return workspace_runtime.terminal_ticket(workspace, int(user["id"]))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Workspace runtime is currently unavailable.") from exc


@router.delete("/repositories/{repository_id}", status_code=204)
def delete_repository_workspace(
    repository_id: int,
    response: Response,
    user: sqlite3.Row = Depends(_current_user),
) -> Response:
    repository = _repository(repository_id, int(user["id"]))
    _require_owner(repository)
    workspace = workspace_runtime.workspace_for_repository(
        int(repository["id"]), int(repository["owner_id"])
    )
    if workspace_runtime.configured():
        try:
            workspace_runtime.delete_workspace(workspace)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="Workspace runtime is currently unavailable.") from exc
    with _db() as db:
        db.execute("DELETE FROM cloud_workspaces WHERE id=?", (workspace["id"],))
        db.commit()
    response.status_code = 204
    return response
