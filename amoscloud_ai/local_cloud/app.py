"""Local-only FastAPI control plane for self-sovereign Amosclaud installations."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .authority import AuthorityError, LocalAuthority
from .executor import ExecutionError, LocalJobManager
from .workspaces import WorkspaceError, WorkspaceRegistry


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    path: str = Field(min_length=1, max_length=4096)


class JobCreate(BaseModel):
    workspace_id: str = Field(pattern=r"^ws_[0-9a-f]{32}$")
    action: str = Field(min_length=1, max_length=80)
    confirmation: str = Field(min_length=1, max_length=200)


class HealAndBuildCreate(BaseModel):
    workspace_id: str = Field(pattern=r"^ws_[0-9a-f]{32}$")
    target: Literal["verify_python", "docker_build"] = "verify_python"
    confirmation: str = Field(min_length=1, max_length=200)


def _state_dir() -> Path:
    configured = os.getenv("AMOSCLAUD_LOCAL_STATE_DIR", "~/.amosclaud/local-cloud")
    return Path(configured).expanduser().resolve()


def _internal_agent_request(request: Request) -> bool:
    if os.getenv("AMOSCLAUD_LOCAL_ALLOW_REMOTE_AGENT", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


def create_app() -> FastAPI:
    application = FastAPI(
        title="Amosclaud Self-Sovereign Cloud Engine",
        version="0.2.0",
        docs_url="/docs",
        redoc_url=None,
    )
    authority = LocalAuthority(_state_dir())
    registry = WorkspaceRegistry(_state_dir())
    jobs = LocalJobManager()

    def require_token(
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        if not authority.initialized():
            raise HTTPException(
                status_code=503,
                detail="Local authority is not initialized. Run scripts/run_local_cloud.py.",
            )
        token = ""
        if authorization and authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ").strip()
        try:
            valid = authority.verify(token)
        except AuthorityError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if not valid:
            raise HTTPException(status_code=401, detail="Local authority token is invalid")

    @application.get("/", response_class=HTMLResponse, include_in_schema=False)
    def dashboard() -> str:
        return """<!doctype html>
<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>
<title>Amosclaud Local Cloud</title><style>
body{font-family:system-ui;max-width:900px;margin:40px auto;padding:0 18px;background:#0c111b;color:#eef3ff}
.card{background:#151d2b;padding:20px;border-radius:14px;margin:14px 0}input,button{padding:10px;border-radius:8px;border:1px solid #526078;margin:4px;background:#0c111b;color:#eef3ff}button{cursor:pointer}pre{white-space:pre-wrap}
</style></head><body><h1>Amosclaud Self-Sovereign Cloud</h1>
<p>Local dashboard. Your token and workspace metadata remain on this installation.</p>
<div class='card'><input id='token' type='password' placeholder='Local authority token'><button onclick='load()'>Connect</button></div>
<div class='card'><h2>Health</h2><pre id='out'>Not connected.</pre></div>
<script>async function load(){const token=document.getElementById('token').value;const r=await fetch('/v1/status',{headers:{Authorization:'Bearer '+token}});document.getElementById('out').textContent=JSON.stringify(await r.json(),null,2)}</script>
</body></html>"""

    @application.get("/live")
    def live() -> dict[str, object]:
        return {
            "status": "ok",
            "mode": "local-first",
            "internet_required": False,
            "authority_initialized": authority.initialized(),
        }

    @application.get("/v1/status", dependencies=[Depends(require_token)])
    def status() -> dict[str, object]:
        state = authority.state()
        return {
            "status": "ready",
            "instance_id": state.instance_id,
            "token_version": state.token_version,
            "state_dir": str(_state_dir()),
            "workspace_count": len(registry.list()),
            "actions": jobs.ACTIONS,
            "agent_api": "/api/agent/heal-and-build",
            "external_identity_required": False,
            "raw_code_uploaded_by_control_plane": False,
        }

    @application.get("/v1/workspaces", dependencies=[Depends(require_token)])
    def list_workspaces() -> list[dict[str, str]]:
        return [workspace.__dict__ for workspace in registry.list()]

    @application.post(
        "/v1/workspaces",
        status_code=201,
        dependencies=[Depends(require_token)],
    )
    def register_workspace(body: WorkspaceCreate) -> dict[str, str]:
        try:
            return registry.register(name=body.name, path=body.path).__dict__
        except WorkspaceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.delete(
        "/v1/workspaces/{workspace_id}",
        status_code=204,
        dependencies=[Depends(require_token)],
    )
    def remove_workspace(workspace_id: str) -> None:
        try:
            registry.remove(workspace_id)
        except WorkspaceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @application.get("/v1/actions", dependencies=[Depends(require_token)])
    def actions() -> dict[str, str]:
        return jobs.ACTIONS

    @application.post("/v1/jobs", status_code=202, dependencies=[Depends(require_token)])
    def create_job(body: JobCreate) -> dict[str, object]:
        try:
            workspace = registry.get(body.workspace_id)
            return jobs.create(
                workspace=workspace,
                action=body.action,
                confirmation=body.confirmation,
            ).__dict__
        except WorkspaceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ExecutionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.post(
        "/api/agent/heal-and-build",
        status_code=202,
        dependencies=[Depends(require_token)],
    )
    def heal_and_build(body: HealAndBuildCreate, request: Request) -> dict[str, object]:
        if not _internal_agent_request(request):
            raise HTTPException(status_code=403, detail="Heal-and-build is loopback-only")
        expected = f"HEAL {body.workspace_id} {body.target}"
        if body.confirmation.strip() != expected:
            raise HTTPException(
                status_code=422,
                detail=f"Confirmation must exactly equal: {expected}",
            )
        action = {
            "verify_python": "guarded_verify_python",
            "docker_build": "guarded_docker_build",
        }[body.target]
        try:
            workspace = registry.get(body.workspace_id)
            job = jobs.create(
                workspace=workspace,
                action=action,
                confirmation=jobs.required_confirmation(workspace.id, action),
            )
        except WorkspaceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ExecutionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            **job.__dict__,
            "target": body.target,
            "status_url": f"/v1/jobs/{job.id}",
            "maximum_attempts": 3,
        }

    @application.get("/v1/jobs", dependencies=[Depends(require_token)])
    def list_jobs() -> list[dict[str, object]]:
        return jobs.list()

    @application.get("/v1/jobs/{job_id}", dependencies=[Depends(require_token)])
    def get_job(job_id: str) -> dict[str, object]:
        try:
            return jobs.get(job_id).__dict__
        except ExecutionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @application.post("/v1/authority/rotate", dependencies=[Depends(require_token)])
    def rotate_token(request: Request) -> dict[str, str]:
        if request.client and request.client.host not in {
            "127.0.0.1",
            "::1",
            "localhost",
        }:
            raise HTTPException(status_code=403, detail="Token rotation is loopback-only")
        return {
            "token": authority.rotate(),
            "warning": "Store this token now; it is shown once.",
        }

    return application


app = create_app()
