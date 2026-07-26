"""Private FastAPI service for isolated Amosclaud workspace containers."""
from __future__ import annotations

import hmac
import os
import shutil
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from workspace_worker import runtime


app = FastAPI(
    title="Amosclaud Workspace Worker",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)


class WorkspaceProvisionRequest(BaseModel):
    workspace_id: str = Field(min_length=11, max_length=67)
    repository_id: int = Field(ge=1)
    cpu: float = Field(default=1.0, gt=0, le=2.0)
    memory_mb: int = Field(default=2048, ge=256, le=4096)
    pids: int = Field(default=256, ge=32, le=512)


def _read_secret(name: str) -> str:
    direct = os.getenv(name, "").strip()
    if direct:
        return direct
    path_value = os.getenv(f"{name}_FILE", "").strip()
    if not path_value:
        return ""
    try:
        path = Path(path_value)
        return path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    except OSError:
        return ""


def _configured_token() -> str:
    return _read_secret("AMOSCLAUD_WORKSPACE_WORKER_TOKEN") or _read_secret(
        "AMOSCLAUD_WORKSPACE_PROVIDER_TOKEN"
    )


def authorize(authorization: str | None = Header(default=None)) -> None:
    token = _configured_token()
    if not token:
        raise HTTPException(
            status_code=503,
            detail="Workspace worker token is not configured",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing workspace worker token")
    supplied = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token, supplied):
        raise HTTPException(status_code=401, detail="Invalid workspace worker token")


def _invoke(operation, *args, **kwargs) -> dict:
    try:
        return operation(*args, **kwargs)
    except runtime.WorkspaceRuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "amosclaud-workspace-worker",
        "docker_available": bool(
            shutil.which(os.getenv("AMOSCLAUD_DOCKER_BINARY", "docker"))
        ),
        "token_configured": bool(_configured_token()),
    }


@app.post("/v1/workspaces", dependencies=[Depends(authorize)])
def provision_workspace(body: WorkspaceProvisionRequest) -> dict:
    return _invoke(
        runtime.provision,
        workspace_id=body.workspace_id,
        repository_id=body.repository_id,
        cpu=body.cpu,
        memory_mb=body.memory_mb,
        pids=body.pids,
    )


@app.get("/v1/workspaces/{workspace_id}", dependencies=[Depends(authorize)])
def workspace_status(workspace_id: str) -> dict:
    try:
        config = runtime.runtime_config()
        return runtime.describe(config, workspace_id)
    except runtime.WorkspaceRuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/workspaces/{workspace_id}/start", dependencies=[Depends(authorize)])
def start_workspace(workspace_id: str) -> dict:
    return _invoke(runtime.start, workspace_id)


@app.post("/v1/workspaces/{workspace_id}/stop", dependencies=[Depends(authorize)])
def stop_workspace(workspace_id: str) -> dict:
    return _invoke(runtime.stop, workspace_id)


@app.post("/v1/workspaces/{workspace_id}/restart", dependencies=[Depends(authorize)])
def restart_workspace(workspace_id: str) -> dict:
    return _invoke(runtime.restart, workspace_id)


@app.delete("/v1/workspaces/{workspace_id}", dependencies=[Depends(authorize)])
def delete_workspace(workspace_id: str) -> dict:
    return _invoke(runtime.delete, workspace_id)
