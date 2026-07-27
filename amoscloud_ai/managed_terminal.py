"""Same-service managed terminal fallback for a single Amosclaud deployment.

The preferred production execution plane remains the isolated workspace runtime.
When that service is not configured or temporarily unreachable, this module keeps
an owner-operated Amosclaud installation usable by running a non-root PTY process
inside the public service with a scrubbed environment and repository-scoped cwd.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import pty
import secrets
import shutil
import signal
import stat
import struct
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect

from amoscloud_ai import workspace_runtime
from amoscloud_ai.api.routes.auth import DB_PATH, get_user_from_session
from amoscloud_ai.api.routes.repositories import (
    REPOSITORY_ROOT,
    _access,
    _db,
    _repo_path,
    _require_owner,
)

_TICKET_TTL_SECONDS = 120
_MAX_SESSIONS_PER_USER = 4
_TICKETS: dict[str, dict[str, Any]] = {}
_TICKET_LOCK = threading.Lock()
_ACTIVE_LOCK = threading.Lock()


@dataclass
class ActiveTerminal:
    workspace_id: str
    repository_id: int
    user_id: int
    terminal_id: str
    process: subprocess.Popen[bytes]
    master_fd: int


_ACTIVE: dict[tuple[int, str], ActiveTerminal] = {}


def enabled() -> bool:
    value = os.getenv("AMOSCLAUD_MANAGED_TERMINAL_ENABLED", "true")
    return value.strip().lower() not in {"0", "false", "no", "off"}


def health(*, external: dict[str, Any] | None = None) -> dict[str, Any]:
    if not enabled():
        return {
            "configured": False,
            "ok": False,
            "provider": "managed",
            "detail": "The managed terminal fallback is disabled.",
        }
    external_detail = str((external or {}).get("detail") or "").strip()
    detail = (
        "Amosclaud managed runtime is ready in this deployment."
        if not external_detail
        else f"Managed runtime ready; isolated runtime unavailable: {external_detail}"
    )
    return {
        "configured": True,
        "ok": True,
        "provider": "managed",
        "mode": "same-service",
        "detail": detail,
        "docker_ready": False,
        "token_configured": True,
        "network": "managed-platform",
        "workspace_image": "amosclaud-public-service",
        "managed_fallback": True,
        "security_boundary": "non-root process with scrubbed environment",
    }


def _provider_detail(workspace: dict[str, Any]) -> str:
    return str(workspace.get("runtime_detail") or "")


def status(workspace: dict[str, Any]) -> dict[str, Any]:
    running = (
        str(workspace.get("runtime_status") or "") == "running"
        and "provider=managed" in _provider_detail(workspace)
    )
    return {
        "workspace_id": workspace["id"],
        "repository_id": int(workspace["repository_id"]),
        "owner_id": int(workspace["owner_id"]),
        "container_id": None,
        "status": "running" if running else "exited",
        "running": running,
        "started_at": workspace.get("last_started_at"),
        "persistent_repository": True,
        "cpu_limit": "platform",
        "memory_mb": "platform",
        "pids_limit": 256,
        "network": "managed-platform",
        "user": "managed-developer",
        "workspace_image": "amosclaud-public-service",
        "provider": "managed",
        "managed_fallback": True,
    }


def start(workspace: dict[str, Any]) -> dict[str, Any]:
    if not enabled():
        raise RuntimeError("Managed terminal fallback is disabled")
    workspace_runtime.record_workspace_status(
        str(workspace["id"]),
        "running",
        "provider=managed; mode=same-service",
        started=True,
    )
    refreshed = dict(workspace)
    refreshed["runtime_status"] = "running"
    refreshed["runtime_detail"] = "provider=managed; mode=same-service"
    refreshed["last_started_at"] = workspace_runtime._now()
    return status(refreshed)


def _terminate(active: ActiveTerminal) -> None:
    try:
        if active.process.poll() is None:
            os.killpg(active.process.pid, signal.SIGTERM)
            try:
                active.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(active.process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        os.close(active.master_fd)
    except OSError:
        pass


def stop(workspace: dict[str, Any]) -> dict[str, Any]:
    workspace_id = str(workspace["id"])
    with _ACTIVE_LOCK:
        matches = [
            key
            for key, active in _ACTIVE.items()
            if active.workspace_id == workspace_id
        ]
        terminals = [_ACTIVE.pop(key) for key in matches]
    for active in terminals:
        _terminate(active)
    workspace_runtime.record_workspace_status(
        workspace_id,
        "exited",
        "provider=managed; mode=same-service",
        stopped=True,
    )
    refreshed = dict(workspace)
    refreshed["runtime_status"] = "exited"
    refreshed["runtime_detail"] = "provider=managed; mode=same-service"
    refreshed["last_stopped_at"] = workspace_runtime._now()
    return status(refreshed)


def delete(workspace: dict[str, Any]) -> None:
    stop(workspace)


def _clean_tickets() -> None:
    now = int(time.time())
    for token, claims in list(_TICKETS.items()):
        if int(claims.get("expires_at") or 0) < now:
            _TICKETS.pop(token, None)


def create_ticket(
    request: Request,
    workspace: dict[str, Any],
    user_id: int,
    *,
    terminal_id: str,
    profile: str,
) -> dict[str, Any]:
    if not enabled():
        raise RuntimeError("Managed terminal fallback is disabled")
    expires_at = int(time.time()) + _TICKET_TTL_SECONDS
    token = secrets.token_urlsafe(32)
    claims = {
        "workspace_id": str(workspace["id"]),
        "repository_id": int(workspace["repository_id"]),
        "owner_id": int(workspace["owner_id"]),
        "user_id": int(user_id),
        "terminal_id": terminal_id,
        "profile": profile,
        "expires_at": expires_at,
    }
    with _TICKET_LOCK:
        _clean_tickets()
        _TICKETS[token] = claims
    url = request.url_for(
        "managed_terminal_websocket",
        repository_id=str(workspace["repository_id"]),
        terminal_id=terminal_id,
    ).include_query_params(ticket=token)
    return {
        "workspace_id": workspace["id"],
        "expires_at": expires_at,
        "websocket_url": str(url),
        "provider": "managed",
        "profile": profile,
    }


def _consume_ticket(token: str) -> dict[str, Any]:
    with _TICKET_LOCK:
        _clean_tickets()
        claims = _TICKETS.pop(token, None)
    if not claims:
        raise HTTPException(status_code=401, detail="Terminal ticket is invalid or expired")
    if int(claims["expires_at"]) < int(time.time()):
        raise HTTPException(status_code=401, detail="Terminal ticket expired")
    return claims


def _developer_uid(user_id: int) -> int:
    # Linux accepts numeric identities without /etc/passwd entries. A stable UID
    # prevents one Amosclaud account from reading another account's repositories.
    return 20_000 + int(user_id)


def _prepare_repository(path: Path, user_id: int) -> tuple[int, Path]:
    repository_root = REPOSITORY_ROOT.resolve()
    target = path.resolve()
    try:
        target.relative_to(repository_root)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="Managed terminal repository path is outside storage root",
        ) from exc
    uid = _developer_uid(user_id)
    target.mkdir(parents=True, exist_ok=True)
    try:
        for root, directories, files in os.walk(target, followlinks=False):
            root_path = Path(root)
            os.chown(root_path, uid, uid, follow_symlinks=False)
            os.chmod(root_path, 0o700, follow_symlinks=False)
            for name in directories + files:
                item = root_path / name
                if item.is_symlink():
                    continue
                mode = stat.S_IMODE(item.stat(follow_symlinks=False).st_mode)
                os.chown(item, uid, uid, follow_symlinks=False)
                if item.is_dir():
                    os.chmod(item, 0o700, follow_symlinks=False)
                else:
                    executable = mode & 0o100
                    os.chmod(item, 0o600 | executable, follow_symlinks=False)
    except PermissionError:
        # Local non-root installations cannot chown. They still run as the server
        # user, with the environment scrubbed and cwd fixed to this repository.
        uid = os.getuid()
    home = Path("/tmp/amosclaud-managed-home") / str(uid)
    home.mkdir(parents=True, exist_ok=True)
    try:
        os.chown(home, uid, uid)
        os.chmod(home, 0o700)
    except PermissionError:
        pass
    try:
        DB_PATH.chmod(0o600)
    except OSError:
        pass
    return uid, home


def _safe_environment(
    *,
    repository_id: int,
    user_id: int,
    home: Path,
    shell: str,
) -> dict[str, str]:
    path = os.getenv(
        "AMOSCLAUD_MANAGED_TERMINAL_PATH",
        "/usr/local/bin:/usr/bin:/bin",
    )
    return {
        "PATH": path,
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TERM": "xterm-256color",
        "COLORTERM": "truecolor",
        "SHELL": shell,
        "USER": "managed-developer",
        "LOGNAME": "managed-developer",
        "PS1": "\\[\\e[1;36m\\]amosclaud\\[\\e[0m\\]:\\w$ ",
        "PYTHONUNBUFFERED": "1",
        "AMOSCLAUD_REPOSITORY_ID": str(repository_id),
        "AMOSCLAUD_WORKSPACE_ROOT": str(_repo_path(repository_id).resolve()),
        "AMOSCLAUD_TERMINAL_PROVIDER": "managed",
        "AMOSCLAUD_TERMINAL_USER_ID": str(user_id),
    }


def _command(profile: str) -> list[str]:
    if profile == "python":
        python = shutil.which("python3") or shutil.which("python")
        if not python:
            raise HTTPException(status_code=503, detail="Python is unavailable")
        return [python, "-i"]
    if profile == "sh":
        return [shutil.which("sh") or "/bin/sh", "-i"]
    return [shutil.which("bash") or "/bin/bash", "--noprofile", "--norc", "-i"]


def _set_child_identity(uid: int) -> None:
    os.umask(0o077)
    if os.geteuid() == 0 and uid != 0:
        os.setgid(uid)
        os.setuid(uid)


def _resize(master_fd: int, rows: int, cols: int) -> None:
    rows = max(2, min(int(rows), 500))
    cols = max(10, min(int(cols), 1000))
    fcntl.ioctl(
        master_fd,
        getattr(__import__("termios"), "TIOCSWINSZ"),
        struct.pack("HHHH", rows, cols, 0, 0),
    )


def _parse_control(text: str) -> dict[str, Any] | None:
    if not text.startswith("{"):
        return None
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("type") not in {"resize", "ping", "terminate"}:
        return None
    return payload


async def websocket_session(
    websocket: WebSocket,
    *,
    repository_id: int,
    terminal_id: str,
) -> None:
    ticket_value = str(websocket.query_params.get("ticket") or "")
    try:
        claims = _consume_ticket(ticket_value)
        user = get_user_from_session(websocket.cookies.get("amos_session"))
        if not user or int(user["id"]) != int(claims["user_id"]):
            raise HTTPException(status_code=401, detail="Terminal session is not authenticated")
        if int(claims["repository_id"]) != int(repository_id):
            raise HTTPException(status_code=401, detail="Terminal repository mismatch")
        if str(claims["terminal_id"]) != terminal_id:
            raise HTTPException(status_code=401, detail="Terminal session mismatch")
        with _db() as db:
            repository = _access(db, repository_id, int(user["id"]))
        _require_owner(repository)
    except HTTPException as exc:
        await websocket.close(code=4401 if exc.status_code == 401 else 4403, reason=str(exc.detail)[:120])
        return

    key = (int(user["id"]), terminal_id)
    with _ACTIVE_LOCK:
        user_sessions = sum(
            1 for active in _ACTIVE.values() if active.user_id == int(user["id"])
        )
        if user_sessions >= _MAX_SESSIONS_PER_USER:
            active = None
        else:
            active = True
    if active is None:
        await websocket.close(code=4429, reason="Managed terminal session limit reached")
        return

    repository_path = _repo_path(repository_id).resolve()
    uid, home = _prepare_repository(repository_path, int(user["id"]))
    command = _command(str(claims["profile"]))
    shell = command[0]
    master_fd, slave_fd = pty.openpty()
    _resize(master_fd, 30, 120)
    try:
        process = subprocess.Popen(
            command,
            cwd=repository_path,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=_safe_environment(
                repository_id=repository_id,
                user_id=int(user["id"]),
                home=home,
                shell=shell,
            ),
            close_fds=True,
            start_new_session=True,
            preexec_fn=(lambda: _set_child_identity(uid)),
        )
    finally:
        os.close(slave_fd)

    terminal = ActiveTerminal(
        workspace_id=str(claims["workspace_id"]),
        repository_id=repository_id,
        user_id=int(user["id"]),
        terminal_id=terminal_id,
        process=process,
        master_fd=master_fd,
    )
    with _ACTIVE_LOCK:
        previous = _ACTIVE.pop(key, None)
        _ACTIVE[key] = terminal
    if previous:
        _terminate(previous)

    await websocket.accept()
    await websocket.send_text(
        "\r\n\x1b[1;32mAmosclaud managed runtime connected\x1b[0m\r\n"
        "Real commands and debugger output will stream here.\r\n\r\n"
    )

    async def reader() -> None:
        while process.poll() is None:
            try:
                data = await asyncio.to_thread(os.read, master_fd, 4096)
            except OSError:
                break
            if not data:
                break
            await websocket.send_bytes(data)
        code = process.poll()
        try:
            await websocket.send_text(
                f"\r\n\x1b[2m[terminal process exited: {code}]\x1b[0m\r\n"
            )
        except RuntimeError:
            pass

    async def receiver() -> None:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            raw_bytes = message.get("bytes")
            raw_text = message.get("text")
            if raw_text is not None:
                control = _parse_control(raw_text)
                if control:
                    if control["type"] == "resize":
                        _resize(
                            master_fd,
                            int(control.get("rows") or 30),
                            int(control.get("cols") or 120),
                        )
                    elif control["type"] == "terminate":
                        _terminate(terminal)
                        break
                    elif control["type"] == "ping":
                        await websocket.send_text("\x1b]777;amos:pong\x07")
                    continue
                raw_bytes = raw_text.encode()
            if raw_bytes:
                try:
                    os.write(master_fd, raw_bytes)
                except OSError:
                    break

    reader_task = asyncio.create_task(reader())
    receiver_task = asyncio.create_task(receiver())
    try:
        done, pending = await asyncio.wait(
            {reader_task, receiver_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            try:
                task.result()
            except (WebSocketDisconnect, RuntimeError, OSError):
                pass
    finally:
        with _ACTIVE_LOCK:
            if _ACTIVE.get(key) is terminal:
                _ACTIVE.pop(key, None)
        _terminate(terminal)
        try:
            await websocket.close(code=1000)
        except RuntimeError:
            pass
