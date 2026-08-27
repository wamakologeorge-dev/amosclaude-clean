"""Browser-safe VS Code terminal bridge for the Amosclaud managed runtime.

Each terminal ticket is short-lived, single-use, bound to one Amosclaud user,
repository, terminal id, and runtime profile. The browser never receives a
platform database credential or a reusable WebSocket credential.
"""

from __future__ import annotations

import asyncio
import os
import pty
import secrets
import subprocess
import threading
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from amoscloud_ai import managed_terminal, workspace_runtime, workspace_terminal
from amoscloud_ai.api.routes.auth import get_user_from_session
from amoscloud_ai.api.routes.autonomous_keys import authenticate_autonomous_key
from amoscloud_ai.api.routes.repositories import (
    _access,
    _db,
    _repo_path,
    _require_write,
)

router = APIRouter(prefix="/vscode-terminal", tags=["vscode-terminal"])

_TICKET_TTL_SECONDS = 120
_TICKETS: dict[str, dict[str, Any]] = {}
_TICKET_LOCK = threading.Lock()


class TerminalTicketRequest(BaseModel):
    terminal_id: str = Field(pattern=r"^term_[a-z0-9]{8,32}$")
    profile: Literal["bash", "sh", "python"] = "bash"


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "").strip()
    scheme, separator, value = authorization.partition(" ")
    if separator and scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return ""


def _user(request: Request):
    """Resolve the human account behind a browser terminal request."""

    user = get_user_from_session(request.cookies.get("amos_session"))
    if user:
        return user
    user = authenticate_autonomous_key(_bearer_token(request))
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Sign in or configure a valid per-user Amosclaud Autonomous key",
        )
    return user


def _accessible_repository(repository_id: int, user_id: int):
    with _db() as db:
        return _access(db, repository_id, user_id)


def _workspace(repository_id: int, user_id: int) -> dict[str, Any]:
    repository = _accessible_repository(repository_id, user_id)
    return workspace_runtime.workspace_for_repository(
        int(repository["id"]),
        int(repository["owner_id"]),
    )


def _clean_tickets() -> None:
    now = int(time.time())
    for token, claims in list(_TICKETS.items()):
        if int(claims.get("expires_at") or 0) < now:
            _TICKETS.pop(token, None)


def _issue_ticket(
    request: Request,
    *,
    repository_id: int,
    user_id: int,
    workspace_id: str,
    terminal_id: str,
    profile: str,
) -> dict[str, Any]:
    token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + _TICKET_TTL_SECONDS
    claims = {
        "repository_id": int(repository_id),
        "user_id": int(user_id),
        "workspace_id": str(workspace_id),
        "terminal_id": terminal_id,
        "profile": profile,
        "expires_at": expires_at,
    }
    with _TICKET_LOCK:
        _clean_tickets()
        _TICKETS[token] = claims

    url = str(
        request.url_for(
            "vscode_terminal_websocket",
            repository_id=str(repository_id),
            terminal_id=terminal_id,
        ).include_query_params(ticket=token)
    )
    if url.startswith("https://"):
        url = "wss://" + url.removeprefix("https://")
    elif url.startswith("http://"):
        url = "ws://" + url.removeprefix("http://")
    return {
        "protocol": "amosclaud-vscode-terminal-v1",
        "repository_id": repository_id,
        "workspace_id": workspace_id,
        "terminal_id": terminal_id,
        "profile": profile,
        "expires_at": expires_at,
        "websocket_url": url,
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


@router.get("/repositories")
def list_terminal_repositories(user=Depends(_user)) -> dict[str, Any]:
    """List repositories the authenticated user may inspect or develop."""

    with _db() as db:
        rows = db.execute(
            """SELECT r.id,r.name,r.description,r.default_branch,r.updated_at,
                      CASE WHEN r.owner_id=? THEN 'owner' ELSE COALESCE(c.role, 'viewer') END AS role
               FROM repositories r
               LEFT JOIN repository_collaborators c
                 ON c.repository_id=r.id AND c.user_id=?
               WHERE r.owner_id=? OR c.user_id=? OR r.visibility='public'
               ORDER BY r.updated_at DESC""",
            (int(user["id"]), int(user["id"]), int(user["id"]), int(user["id"])),
        ).fetchall()
    return {
        "repositories": [dict(row) for row in rows],
        "count": len(rows),
        "terminal_profiles": ["bash", "sh", "python"],
        "max_sessions_per_user": managed_terminal._MAX_SESSIONS_PER_USER,
    }


@router.post("/repositories/{repository_id}/start")
def start_terminal_workspace(
    repository_id: int,
    user=Depends(_user),
) -> dict[str, Any]:
    """Start an isolated workspace, using a managed developer fallback if needed."""

    repository = _accessible_repository(repository_id, int(user["id"]))
    workspace = workspace_runtime.workspace_for_repository(
        int(repository["id"]),
        int(repository["owner_id"]),
    )
    can_write = str(repository["role"] or "viewer") in {"owner", "developer"}
    external = workspace_runtime.runtime_health()
    if external.get("ok"):
        try:
            container = workspace_runtime.start_workspace(
                workspace,
                environment={
                    "AMOSCLAUD_PROJECT_REPOSITORY_ID": str(repository_id),
                    "AMOSCLAUD_PROJECT_OWNER_ID": str(workspace["owner_id"]),
                },
                read_only=not can_write,
            )
            return {
                "workspace": workspace,
                "container": container,
                "provider": "external",
                "access": {
                    "role": str(repository["role"] or "viewer"),
                    "can_write": can_write,
                    "terminal_mode": "writable" if can_write else "read-only",
                },
                "user_id": int(user["id"]),
            }
        except RuntimeError as exc:
            if "different access mode" in str(exc).casefold():
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            if not can_write:
                raise HTTPException(
                    status_code=503,
                    detail="A read-only Docker workspace could not be started.",
                ) from exc

    _require_write(repository)
    try:
        container = managed_terminal.start(workspace)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "workspace": workspace,
        "container": container,
        "provider": "managed",
        "access": {
            "role": str(repository["role"] or "viewer"),
            "can_write": True,
            "terminal_mode": "writable",
        },
        "user_id": int(user["id"]),
    }


@router.post("/repositories/{repository_id}/ticket")
def create_terminal_ticket(
    repository_id: int,
    body: TerminalTicketRequest,
    request: Request,
    user=Depends(_user),
) -> dict[str, Any]:
    """Issue one browser WebSocket ticket for an already started workspace."""

    repository = _accessible_repository(repository_id, int(user["id"]))
    workspace = workspace_runtime.workspace_for_repository(
        int(repository["id"]),
        int(repository["owner_id"]),
    )
    external = workspace_runtime.runtime_health()
    if external.get("ok"):
        try:
            container = workspace_runtime.remote_status(workspace)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail="The isolated workspace runtime is temporarily unreachable.",
            ) from exc
        if not container.get("running"):
            raise HTTPException(status_code=409, detail="Start the Amosclaud workspace first")
        can_write = str(repository["role"] or "viewer") in {"owner", "developer"}
        if not can_write and not bool(container.get("read_only")):
            raise HTTPException(
                status_code=409,
                detail="Restart the workspace in read-only mode before opening it as a viewer",
            )
        try:
            return workspace_terminal.terminal_ticket(
                workspace,
                int(user["id"]),
                terminal_id=body.terminal_id,
                profile=body.profile,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="Workspace terminal is unavailable") from exc

    _require_write(repository)
    if not managed_terminal.status(workspace).get("running"):
        raise HTTPException(status_code=409, detail="Start the Amosclaud workspace first")
    return _issue_ticket(
        request,
        repository_id=repository_id,
        user_id=int(user["id"]),
        workspace_id=str(workspace["id"]),
        terminal_id=body.terminal_id,
        profile=body.profile,
    )


@router.websocket(
    "/repositories/{repository_id}/terminal/{terminal_id}",
    name="vscode_terminal_websocket",
)
async def vscode_terminal_websocket(
    websocket: WebSocket,
    repository_id: int,
    terminal_id: str,
) -> None:
    """Bridge one VS Code Pseudoterminal to a repository-scoped Linux PTY."""

    try:
        claims = _consume_ticket(str(websocket.query_params.get("ticket") or ""))
        if int(claims["repository_id"]) != int(repository_id):
            raise HTTPException(status_code=401, detail="Terminal repository mismatch")
        if str(claims["terminal_id"]) != terminal_id:
            raise HTTPException(status_code=401, detail="Terminal session mismatch")
        repository = _accessible_repository(repository_id, int(claims["user_id"]))
        _require_write(repository)
    except HTTPException as exc:
        await websocket.close(
            code=4401 if exc.status_code == 401 else 4403,
            reason=str(exc.detail)[:120],
        )
        return

    user_id = int(claims["user_id"])
    key = (user_id, terminal_id)
    with managed_terminal._ACTIVE_LOCK:
        user_sessions = sum(
            1 for active in managed_terminal._ACTIVE.values() if active.user_id == user_id
        )
        allowed = user_sessions < managed_terminal._MAX_SESSIONS_PER_USER
    if not allowed:
        await websocket.close(code=4429, reason="Managed terminal session limit reached")
        return

    repository_path = _repo_path(int(repository["id"])).resolve()
    uid, home = managed_terminal._prepare_repository(repository_path, user_id)
    command = managed_terminal._command(str(claims["profile"]))
    shell = command[0]
    master_fd, slave_fd = pty.openpty()
    managed_terminal._resize(master_fd, 30, 120)
    try:
        process = subprocess.Popen(
            command,
            cwd=repository_path,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=managed_terminal._safe_environment(
                repository_id=repository_id,
                user_id=user_id,
                home=home,
                shell=shell,
            ),
            close_fds=True,
            start_new_session=True,
            preexec_fn=lambda: managed_terminal._set_child_identity(uid),
        )
    finally:
        os.close(slave_fd)

    terminal = managed_terminal.ActiveTerminal(
        workspace_id=str(claims["workspace_id"]),
        repository_id=repository_id,
        user_id=user_id,
        terminal_id=terminal_id,
        process=process,
        master_fd=master_fd,
    )
    with managed_terminal._ACTIVE_LOCK:
        previous = managed_terminal._ACTIVE.pop(key, None)
        managed_terminal._ACTIVE[key] = terminal
    if previous:
        managed_terminal._terminate(previous)

    await websocket.accept()
    await websocket.send_text(
        "\r\n\x1b[1;32mAmosclaud self terminal connected\x1b[0m\r\n"
        f"Repository: {repository['name']} | User: {user_id} | Profile: {claims['profile']}\r\n\r\n"
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
            await websocket.send_text(f"\r\n\x1b[2m[terminal process exited: {code}]\x1b[0m\r\n")
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
                control = managed_terminal._parse_control(raw_text)
                if control:
                    if control["type"] == "resize":
                        managed_terminal._resize(
                            master_fd,
                            int(control.get("rows") or 30),
                            int(control.get("cols") or 120),
                        )
                    elif control["type"] == "terminate":
                        managed_terminal._terminate(terminal)
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
        with managed_terminal._ACTIVE_LOCK:
            if managed_terminal._ACTIVE.get(key) is terminal:
                managed_terminal._ACTIVE.pop(key, None)
        managed_terminal._terminate(terminal)
        try:
            await websocket.close(code=1000)
        except RuntimeError:
            pass
