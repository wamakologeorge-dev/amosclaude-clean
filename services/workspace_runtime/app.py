"""Dedicated execution-plane service for Amosclaud cloud workspaces.

This service must run on a separate container host. The public Amosclaud API never
receives the Docker socket; it talks to this service through an authenticated
private-network API.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import pty
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import docker
from docker.errors import DockerException, NotFound
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

app = FastAPI(title="Amosclaud Workspace Runtime", version="1.0.0")

_ID_RE = re.compile(r"^ws_[a-z0-9]{12,48}$")
RUNTIME_TOKEN = os.getenv("AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN", "").strip()
STORAGE_ROOT = Path(
    os.getenv("AMOSCLAUD_WORKSPACE_STORAGE_ROOT", "/var/lib/amosclaud/workspaces")
).resolve()
WORKSPACE_IMAGE = os.getenv(
    "AMOSCLAUD_WORKSPACE_IMAGE", "amosclaud/workspace-base:latest"
).strip()
WORKSPACE_NETWORK = os.getenv("AMOSCLAUD_WORKSPACE_NETWORK", "none").strip()
CPU_LIMIT = min(max(float(os.getenv("AMOSCLAUD_WORKSPACE_CPU", "2")), 0.25), 2.0)
MEMORY_LIMIT = min(max(int(os.getenv("AMOSCLAUD_WORKSPACE_MEMORY_MB", "4096")), 256), 4096)
PIDS_LIMIT = min(max(int(os.getenv("AMOSCLAUD_WORKSPACE_PIDS", "512")), 64), 512)
IDLE_TIMEOUT_SECONDS = min(
    max(int(os.getenv("AMOSCLAUD_WORKSPACE_IDLE_TIMEOUT_SECONDS", "1800")), 300),
    86400,
)


class WorkspaceStart(BaseModel):
    workspace_id: str
    repository_id: int = Field(gt=0)
    owner_id: int = Field(gt=0)
    environment: dict[str, str] = Field(default_factory=dict)


class TerminalTicket(BaseModel):
    workspace_id: str
    user_id: int = Field(gt=0)
    expires_at: int = Field(gt=0)
    signature: str = Field(min_length=64, max_length=64)


def _docker():
    try:
        return docker.from_env(timeout=15)
    except DockerException as exc:
        raise HTTPException(status_code=503, detail="Docker runtime is unavailable") from exc


def _require_token(authorization: str | None) -> None:
    if not RUNTIME_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN is not configured",
        )
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not supplied or not hmac.compare_digest(supplied, RUNTIME_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid runtime authorization")


def _workspace_id(value: str) -> str:
    candidate = value.strip().lower()
    if not _ID_RE.fullmatch(candidate):
        raise HTTPException(status_code=422, detail="Invalid workspace identifier")
    return candidate


def _workspace_path(workspace_id: str) -> Path:
    target = (STORAGE_ROOT / _workspace_id(workspace_id)).resolve()
    if STORAGE_ROOT not in target.parents:
        raise HTTPException(status_code=422, detail="Invalid workspace path")
    return target


def _container_name(workspace_id: str) -> str:
    return f"amosclaud-{_workspace_id(workspace_id)}"


def _safe_environment(values: dict[str, str]) -> dict[str, str]:
    allowed_prefixes = ("AMOSCLAUD_PROJECT_", "PROJECT_", "CI_")
    safe: dict[str, str] = {}
    for key, value in values.items():
        if not key.startswith(allowed_prefixes):
            continue
        if len(key) > 100 or len(value) > 4000 or "\x00" in value:
            continue
        safe[key] = value
    return safe


def _public(container) -> dict[str, Any]:
    container.reload()
    state = container.attrs.get("State") or {}
    labels = (container.attrs.get("Config") or {}).get("Labels") or {}
    return {
        "workspace_id": labels.get("amosclaud.workspace_id"),
        "repository_id": int(labels.get("amosclaud.repository_id") or 0),
        "owner_id": int(labels.get("amosclaud.owner_id") or 0),
        "container_id": container.short_id,
        "status": state.get("Status") or container.status,
        "running": bool(state.get("Running")),
        "started_at": state.get("StartedAt"),
        "persistent_path": labels.get("amosclaud.storage_path"),
        "cpu_limit": CPU_LIMIT,
        "memory_mb": MEMORY_LIMIT,
        "network": WORKSPACE_NETWORK,
    }


def _container(workspace_id: str):
    try:
        return _docker().containers.get(_container_name(workspace_id))
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="Workspace container not found") from exc


def _ticket_payload(ticket: TerminalTicket) -> bytes:
    return f"{ticket.workspace_id}:{ticket.user_id}:{ticket.expires_at}".encode()


def _verify_ticket(ticket_value: str, workspace_id: str) -> TerminalTicket:
    if not RUNTIME_TOKEN:
        raise HTTPException(status_code=503, detail="Runtime token is not configured")
    try:
        padding = "=" * (-len(ticket_value) % 4)
        raw = base64.urlsafe_b64decode(ticket_value + padding)
        ticket = TerminalTicket.model_validate(json.loads(raw))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid terminal ticket") from exc
    if ticket.workspace_id != _workspace_id(workspace_id):
        raise HTTPException(status_code=401, detail="Terminal ticket workspace mismatch")
    if ticket.expires_at < int(time.time()):
        raise HTTPException(status_code=401, detail="Terminal ticket expired")
    expected = hmac.new(
        RUNTIME_TOKEN.encode(), _ticket_payload(ticket), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, ticket.signature):
        raise HTTPException(status_code=401, detail="Invalid terminal ticket signature")
    return ticket


@app.get("/health")
def health() -> dict[str, Any]:
    docker_ready = False
    try:
        docker_ready = bool(_docker().ping())
    except HTTPException:
        pass
    return {
        "ok": docker_ready and bool(RUNTIME_TOKEN),
        "docker_ready": docker_ready,
        "token_configured": bool(RUNTIME_TOKEN),
        "workspace_image": WORKSPACE_IMAGE,
        "cpu_limit": CPU_LIMIT,
        "memory_mb": MEMORY_LIMIT,
        "network": WORKSPACE_NETWORK,
    }


@app.post("/v1/workspaces", status_code=201)
def start_workspace(
    body: WorkspaceStart,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_token(authorization)
    workspace_id = _workspace_id(body.workspace_id)
    storage = _workspace_path(workspace_id)
    storage.mkdir(parents=True, exist_ok=True)
    os.chmod(storage, 0o770)
    client = _docker()
    name = _container_name(workspace_id)
    try:
        container = client.containers.get(name)
        container.reload()
        if not container.attrs.get("State", {}).get("Running"):
            container.start()
        return _public(container)
    except NotFound:
        pass

    network_kwargs: dict[str, Any]
    if WORKSPACE_NETWORK == "none":
        network_kwargs = {"network_mode": "none"}
    else:
        network_kwargs = {"network": WORKSPACE_NETWORK}

    try:
        container = client.containers.run(
            WORKSPACE_IMAGE,
            name=name,
            command=["sleep", "infinity"],
            detach=True,
            tty=True,
            stdin_open=True,
            user="developer",
            working_dir="/workspace",
            environment=_safe_environment(body.environment),
            volumes={str(storage): {"bind": "/workspace", "mode": "rw"}},
            labels={
                "amosclaud.managed": "true",
                "amosclaud.workspace_id": workspace_id,
                "amosclaud.repository_id": str(body.repository_id),
                "amosclaud.owner_id": str(body.owner_id),
                "amosclaud.storage_path": str(storage),
                "amosclaud.last_activity": str(int(time.time())),
            },
            nano_cpus=int(CPU_LIMIT * 1_000_000_000),
            mem_limit=f"{MEMORY_LIMIT}m",
            memswap_limit=f"{MEMORY_LIMIT}m",
            pids_limit=PIDS_LIMIT,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            read_only=True,
            tmpfs={
                "/tmp": "rw,noexec,nosuid,size=512m",
                "/home/developer/.cache": "rw,noexec,nosuid,size=256m,uid=1000,gid=1000",
            },
            **network_kwargs,
        )
    except DockerException as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Workspace container could not start: {type(exc).__name__}",
        ) from exc
    return _public(container)


@app.get("/v1/workspaces/{workspace_id}")
def workspace_status(
    workspace_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_token(authorization)
    return _public(_container(workspace_id))


@app.post("/v1/workspaces/{workspace_id}/stop")
def stop_workspace(
    workspace_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_token(authorization)
    container = _container(workspace_id)
    container.stop(timeout=10)
    return _public(container)


@app.delete("/v1/workspaces/{workspace_id}", status_code=204)
def delete_workspace(
    workspace_id: str,
    authorization: str | None = Header(default=None),
) -> None:
    _require_token(authorization)
    try:
        _container(workspace_id).remove(force=True)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
    if os.getenv("AMOSCLAUD_WORKSPACE_DELETE_STORAGE", "false").lower() == "true":
        shutil.rmtree(_workspace_path(workspace_id), ignore_errors=True)


async def _read_terminal(master_fd: int, websocket: WebSocket) -> None:
    while True:
        data = await asyncio.to_thread(os.read, master_fd, 8192)
        if not data:
            return
        await websocket.send_bytes(data)


async def _write_terminal(master_fd: int, websocket: WebSocket) -> None:
    while True:
        message = await websocket.receive()
        if message.get("type") == "websocket.disconnect":
            return
        data = message.get("bytes")
        if data is None and message.get("text") is not None:
            data = message["text"].encode()
        if data:
            await asyncio.to_thread(os.write, master_fd, data)


@app.websocket("/v1/terminal/{workspace_id}")
async def terminal(websocket: WebSocket, workspace_id: str, ticket: str) -> None:
    try:
        _verify_ticket(ticket, workspace_id)
        container = _container(workspace_id)
        container.reload()
        if not container.attrs.get("State", {}).get("Running"):
            raise HTTPException(status_code=409, detail="Workspace is not running")
    except HTTPException as exc:
        await websocket.close(code=4400 + min(exc.status_code, 99), reason=str(exc.detail))
        return

    await websocket.accept()
    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        [
            "docker",
            "exec",
            "-it",
            "--user",
            "developer",
            "--workdir",
            "/workspace",
            container.name,
            "/bin/bash",
            "-l",
        ],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
        start_new_session=True,
    )
    os.close(slave_fd)
    try:
        reader = asyncio.create_task(_read_terminal(master_fd, websocket))
        writer = asyncio.create_task(_write_terminal(master_fd, websocket))
        done, pending = await asyncio.wait(
            {reader, writer}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        for task in done:
            task.result()
    except (WebSocketDisconnect, OSError, asyncio.CancelledError):
        pass
    finally:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
        os.close(master_fd)
        try:
            await websocket.close()
        except RuntimeError:
            pass


@app.post("/v1/maintenance/stop-idle")
def stop_idle_workspaces(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_token(authorization)
    stopped: list[str] = []
    cutoff = int(time.time()) - IDLE_TIMEOUT_SECONDS
    for container in _docker().containers.list(
        filters={"label": "amosclaud.managed=true"}
    ):
        labels = (container.attrs.get("Config") or {}).get("Labels") or {}
        last_activity = int(labels.get("amosclaud.last_activity") or 0)
        if last_activity and last_activity < cutoff:
            container.stop(timeout=10)
            stopped.append(labels.get("amosclaud.workspace_id") or container.name)
    return {"stopped": stopped, "count": len(stopped)}
