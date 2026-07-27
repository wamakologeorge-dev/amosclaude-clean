"""Dedicated execution-plane service for Amosclaud cloud workspaces.

Run this service on a separate container host. The public Amosclaud API never
receives the Docker socket; it communicates with this service through an
authenticated private-network API.
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
import stat
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
REPOSITORY_STORAGE_ROOT = Path(
    os.getenv(
        "AMOSCLAUD_REPOSITORY_STORAGE_ROOT",
        "/var/lib/amosclaud/repositories",
    )
).resolve()
RUNTIME_STATE_ROOT = Path(
    os.getenv(
        "AMOSCLAUD_WORKSPACE_STATE_ROOT",
        "/var/lib/amosclaud/runtime-state",
    )
).resolve()
POLICY_PATH = Path(
    os.getenv(
        "AMOSCLAUD_ORGANIZATION_SETTINGS",
        "/etc/amosclaud/organization-settings.json",
    )
).resolve()
WORKSPACE_UID = 1000
WORKSPACE_GID = 1000
WORKSPACE_USER = "developer"


def _load_policy() -> dict[str, Any]:
    if not POLICY_PATH.exists():
        return {}
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("server_managed") is not True:
        raise RuntimeError("Workspace policy must be a server-managed JSON object")
    return payload


POLICY = _load_policy()
SANDBOX_POLICY = POLICY.get("sandbox_resource_limits") or {}
WORKSPACE_IMAGE = str(
    POLICY.get("default_sandbox_image") or "amosclaud/workspace-base:latest"
).strip()
CPU_LIMIT = min(max(float(SANDBOX_POLICY.get("max_cpu_cores", 2)), 0.25), 2.0)
MEMORY_LIMIT = min(
    max(int(SANDBOX_POLICY.get("max_memory_mb", 4096)), 256),
    4096,
)
PIDS_LIMIT = min(
    max(int(SANDBOX_POLICY.get("max_processes", 512)), 64),
    512,
)
IDLE_TIMEOUT_SECONDS = min(
    max(int(SANDBOX_POLICY.get("idle_timeout_seconds", 1800)), 300),
    86400,
)
WORKSPACE_NETWORK = "none"
if SANDBOX_POLICY.get("run_as_user", WORKSPACE_USER) != WORKSPACE_USER:
    raise RuntimeError("Workspace policy must use the fixed non-root developer identity")
if SANDBOX_POLICY.get("allow_internal_mesh_access", False) is not False:
    raise RuntimeError("Workspace policy must deny internal platform mesh access")

ALLOWED_ORIGINS = {
    item.strip().rstrip("/")
    for item in os.getenv(
        "AMOSCLAUD_WORKSPACE_ALLOWED_ORIGINS",
        "https://amosclaud.com,https://www.amosclaud.com,http://localhost:8000",
    ).split(",")
    if item.strip()
}
_USED_TICKETS: dict[str, int] = {}


class WorkspaceStart(BaseModel):
    workspace_id: str
    repository_id: int = Field(gt=0)
    owner_id: int = Field(gt=0)
    environment: dict[str, str] = Field(default_factory=dict)


class TerminalTicket(BaseModel):
    workspace_id: str
    user_id: int = Field(gt=0)
    expires_at: int = Field(gt=0)
    nonce: str = Field(min_length=16, max_length=200)
    signature: str = Field(min_length=64, max_length=64)


def _docker():
    try:
        return docker.from_env(timeout=15)
    except DockerException as exc:
        raise HTTPException(
            status_code=503,
            detail="Docker runtime is unavailable",
        ) from exc


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


def _workspace_activity_filename(workspace_id: str) -> str:
    workspace = _workspace_id(workspace_id)
    if not re.fullmatch(r"[a-z0-9_-]+", workspace):
        raise HTTPException(status_code=422, detail="Invalid workspace identifier")
    return f"{workspace}.activity"


def _repository_path(repository_id: int) -> Path:
    if isinstance(repository_id, bool) or repository_id <= 0:
        raise HTTPException(status_code=422, detail="Invalid repository identifier")
    target = (REPOSITORY_STORAGE_ROOT / str(repository_id)).resolve()
    try:
        target.relative_to(REPOSITORY_STORAGE_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid repository path") from exc
    return target


def _activity_path(workspace_id: str) -> Path:
    RUNTIME_STATE_ROOT.mkdir(parents=True, exist_ok=True)
    root = RUNTIME_STATE_ROOT.resolve()
    activity_filename = _workspace_activity_filename(workspace_id)
    target = (root / activity_filename).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid runtime state path") from exc
    return target


def _touch_activity(workspace_id: str) -> None:
    _activity_path(workspace_id).touch(exist_ok=True)


def _prepare_repository_storage(storage: Path) -> None:
    """Prepare one repository for the fixed non-root workspace identity.

    Symlinks are never followed. Directory and file modes are exact, so existing
    world-writable bits are not preserved. Executable files retain only their
    owner/group executable bits. Default ACLs cover future control-plane writes.
    """

    storage.mkdir(parents=True, exist_ok=True)
    directories: list[str] = []
    try:
        for root, names, files in os.walk(storage, followlinks=False):
            paths = [Path(root)] + [Path(root) / name for name in names + files]
            for path in paths:
                os.chown(
                    path,
                    WORKSPACE_UID,
                    WORKSPACE_GID,
                    follow_symlinks=False,
                )
                if path.is_symlink():
                    continue
                mode = stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
                if path.is_dir():
                    os.chmod(path, 0o2770, follow_symlinks=False)
                    directories.append(str(path))
                else:
                    executable = mode & 0o110
                    os.chmod(path, 0o660 | executable, follow_symlinks=False)
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Persistent repository storage cannot apply the fixed "
                "non-root developer ownership."
            ),
        ) from exc

    for offset in range(0, len(directories), 200):
        result = subprocess.run(
            [
                "setfacl",
                "-m",
                f"u:{WORKSPACE_UID}:rwx",
                "-m",
                f"d:u:{WORKSPACE_UID}:rwx",
                *directories[offset : offset + 200],
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Persistent repository storage must support POSIX ACLs or use "
                    "the fixed UID/GID 1000 for both the control plane and workspace."
                ),
            )


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


def _container(workspace_id: str):
    try:
        return _docker().containers.get(_container_name(workspace_id))
    except NotFound as exc:
        raise HTTPException(
            status_code=404,
            detail="Workspace container not found",
        ) from exc


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
        "persistent_repository": True,
        "cpu_limit": CPU_LIMIT,
        "memory_mb": MEMORY_LIMIT,
        "pids_limit": PIDS_LIMIT,
        "network": WORKSPACE_NETWORK,
        "user": WORKSPACE_USER,
        "workspace_image": WORKSPACE_IMAGE,
    }


def _ticket_payload(ticket: TerminalTicket) -> bytes:
    return (
        f"{ticket.workspace_id}:{ticket.user_id}:"
        f"{ticket.expires_at}:{ticket.nonce}"
    ).encode()


def _verify_ticket(ticket_value: str, workspace_id: str) -> TerminalTicket:
    if not RUNTIME_TOKEN:
        raise HTTPException(status_code=503, detail="Runtime token is not configured")
    try:
        padding = "=" * (-len(ticket_value) % 4)
        raw = base64.urlsafe_b64decode(ticket_value + padding)
        ticket = TerminalTicket.model_validate(json.loads(raw))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid terminal ticket") from exc
    now = int(time.time())
    for nonce, expires_at in list(_USED_TICKETS.items()):
        if expires_at < now:
            _USED_TICKETS.pop(nonce, None)
    if ticket.workspace_id != _workspace_id(workspace_id):
        raise HTTPException(
            status_code=401,
            detail="Terminal ticket workspace mismatch",
        )
    if ticket.expires_at < now:
        raise HTTPException(status_code=401, detail="Terminal ticket expired")
    if ticket.nonce in _USED_TICKETS:
        raise HTTPException(status_code=401, detail="Terminal ticket was already used")
    expected = hmac.new(
        RUNTIME_TOKEN.encode(),
        _ticket_payload(ticket),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, ticket.signature):
        raise HTTPException(status_code=401, detail="Invalid terminal ticket signature")
    _USED_TICKETS[ticket.nonce] = ticket.expires_at
    return ticket


def _verify_origin(websocket: WebSocket) -> None:
    origin = (websocket.headers.get("origin") or "").rstrip("/")
    if origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="Untrusted terminal origin")


@app.get("/live")
def live() -> dict[str, bool]:
    return {"ok": True}


@app.get("/health")
def health(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_token(authorization)
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
        "policy_path": str(POLICY_PATH),
        "cpu_limit": CPU_LIMIT,
        "memory_mb": MEMORY_LIMIT,
        "pids_limit": PIDS_LIMIT,
        "network": WORKSPACE_NETWORK,
        "allowed_origins": sorted(ALLOWED_ORIGINS),
    }


@app.post("/v1/workspaces", status_code=201)
def start_workspace(
    body: WorkspaceStart,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_token(authorization)
    workspace_id = _workspace_id(body.workspace_id)
    storage = _repository_path(body.repository_id)
    _prepare_repository_storage(storage)
    _touch_activity(workspace_id)

    client = _docker()
    name = _container_name(workspace_id)
    try:
        container = client.containers.get(name)
        labels = (container.attrs.get("Config") or {}).get("Labels") or {}
        if int(labels.get("amosclaud.repository_id") or 0) != body.repository_id:
            raise HTTPException(
                status_code=409,
                detail="Workspace identifier is already bound to another repository",
            )
        if labels.get("amosclaud.workspace_image") != WORKSPACE_IMAGE:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Workspace image policy changed; remove this stopped container "
                    "before starting it again."
                ),
            )
        container.reload()
        if not container.attrs.get("State", {}).get("Running"):
            container.start()
        return _public(container)
    except NotFound:
        pass

    try:
        container = client.containers.run(
            WORKSPACE_IMAGE,
            name=name,
            command=["sleep", "infinity"],
            detach=True,
            tty=True,
            stdin_open=True,
            user=WORKSPACE_USER,
            working_dir="/workspace",
            environment=_safe_environment(body.environment),
            volumes={str(storage): {"bind": "/workspace", "mode": "rw"}},
            labels={
                "amosclaud.managed": "true",
                "amosclaud.workspace_id": workspace_id,
                "amosclaud.repository_id": str(body.repository_id),
                "amosclaud.owner_id": str(body.owner_id),
                "amosclaud.storage_path": str(storage),
                "amosclaud.workspace_image": WORKSPACE_IMAGE,
            },
            nano_cpus=int(CPU_LIMIT * 1_000_000_000),
            mem_limit=f"{MEMORY_LIMIT}m",
            memswap_limit=f"{MEMORY_LIMIT}m",
            pids_limit=PIDS_LIMIT,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            read_only=True,
            network_mode=WORKSPACE_NETWORK,
            tmpfs={
                "/tmp": "rw,noexec,nosuid,size=512m",
                "/home/developer/.cache": (
                    "rw,noexec,nosuid,size=256m,uid=1000,gid=1000"
                ),
            },
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
    repository_id = 0
    try:
        container = _container(workspace_id)
        labels = (container.attrs.get("Config") or {}).get("Labels") or {}
        repository_id = int(labels.get("amosclaud.repository_id") or 0)
        container.remove(force=True)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
    _activity_path(workspace_id).unlink(missing_ok=True)
    if (
        repository_id
        and os.getenv("AMOSCLAUD_WORKSPACE_DELETE_STORAGE", "false").lower()
        == "true"
    ):
        shutil.rmtree(_repository_path(repository_id), ignore_errors=True)


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


async def _terminal_heartbeat(workspace_id: str) -> None:
    interval = max(15, min(60, IDLE_TIMEOUT_SECONDS // 4))
    while True:
        await asyncio.sleep(interval)
        await asyncio.to_thread(_touch_activity, workspace_id)


@app.websocket("/v1/terminal/{workspace_id}")
async def terminal(websocket: WebSocket, workspace_id: str, ticket: str) -> None:
    try:
        _verify_origin(websocket)
        _verify_ticket(ticket, workspace_id)
        container = _container(workspace_id)
        container.reload()
        if not container.attrs.get("State", {}).get("Running"):
            raise HTTPException(status_code=409, detail="Workspace is not running")
        labels = (container.attrs.get("Config") or {}).get("Labels") or {}
        repository_id = int(labels.get("amosclaud.repository_id") or 0)
        _prepare_repository_storage(_repository_path(repository_id))
        _touch_activity(workspace_id)
    except HTTPException as exc:
        await websocket.close(
            code=4400 + min(exc.status_code, 99),
            reason=str(exc.detail),
        )
        return

    await websocket.accept()
    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        [
            "docker",
            "exec",
            "-it",
            "--user",
            WORKSPACE_USER,
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
    heartbeat = asyncio.create_task(_terminal_heartbeat(workspace_id))
    try:
        reader = asyncio.create_task(_read_terminal(master_fd, websocket))
        writer = asyncio.create_task(_write_terminal(master_fd, websocket))
        done, pending = await asyncio.wait(
            {reader, writer},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            task.result()
    except (WebSocketDisconnect, OSError, asyncio.CancelledError):
        pass
    finally:
        heartbeat.cancel()
        try:
            await heartbeat
        except asyncio.CancelledError:
            pass
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
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
    cutoff = time.time() - IDLE_TIMEOUT_SECONDS
    for container in _docker().containers.list(
        filters={"label": "amosclaud.managed=true"}
    ):
        labels = (container.attrs.get("Config") or {}).get("Labels") or {}
        workspace_id = labels.get("amosclaud.workspace_id") or ""
        marker = _activity_path(workspace_id)
        if marker.exists() and marker.stat().st_mtime < cutoff:
            container.stop(timeout=10)
            stopped.append(workspace_id or container.name)
    return {"stopped": stopped, "count": len(stopped)}
