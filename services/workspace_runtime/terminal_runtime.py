"""Versioned complete terminal transport for the workspace runtime.

This module imports the existing runtime app so all health, lifecycle, and
maintenance endpoints remain unchanged, then adds the v2 WebSocket transport.
The v1 terminal remains available for older clients.
"""

from __future__ import annotations

import asyncio
import base64
import fcntl
import hashlib
import hmac
import json
import os
import pty
import signal
import struct
import subprocess
import termios
import time
from typing import Literal

from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app import (
    IDLE_TIMEOUT_SECONDS,
    RUNTIME_TOKEN,
    WORKSPACE_USER,
    _USED_TICKETS,
    _container,
    _prepare_repository_storage,
    _repository_path,
    _touch_activity,
    _verify_origin,
    _workspace_id,
    app,
)


class TerminalTicketV2(BaseModel):
    version: Literal[2]
    workspace_id: str
    user_id: int = Field(gt=0)
    expires_at: int = Field(gt=0)
    nonce: str = Field(min_length=16, max_length=200)
    terminal_id: str = Field(pattern=r"^term_[a-z0-9]{8,32}$")
    profile: Literal["bash", "sh", "python"]
    signature: str = Field(min_length=64, max_length=64)


def _ticket_payload(ticket: TerminalTicketV2) -> bytes:
    return (
        f"v2:{ticket.workspace_id}:{ticket.user_id}:{ticket.expires_at}:"
        f"{ticket.nonce}:{ticket.terminal_id}:{ticket.profile}"
    ).encode()


def _verify_ticket_v2(ticket_value: str, workspace_id: str) -> TerminalTicketV2:
    if not RUNTIME_TOKEN:
        raise HTTPException(status_code=503, detail="Runtime token is not configured")
    try:
        padding = "=" * (-len(ticket_value) % 4)
        raw = base64.urlsafe_b64decode(ticket_value + padding)
        ticket = TerminalTicketV2.model_validate(json.loads(raw))
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


def _terminal_profile_command(profile: str) -> list[str]:
    commands = {
        "bash": ["/bin/bash", "-l"],
        "sh": ["/bin/sh"],
        "python": ["/usr/bin/python3", "-q"],
    }
    try:
        return commands[profile]
    except KeyError as exc:
        raise HTTPException(status_code=422, detail="Unsupported terminal profile") from exc


def _docker_exec_command(
    container_name: str,
    ticket: TerminalTicketV2,
) -> list[str]:
    return [
        "docker",
        "exec",
        "-it",
        "--user",
        WORKSPACE_USER,
        "--workdir",
        "/workspace",
        "--env",
        "TERM=xterm-256color",
        "--env",
        "COLORTERM=truecolor",
        "--env",
        f"AMOSCLAUD_TERMINAL_ID={ticket.terminal_id}",
        container_name,
        "tmux",
        "new-session",
        "-A",
        "-s",
        ticket.terminal_id,
        "-n",
        ticket.profile,
        *_terminal_profile_command(ticket.profile),
    ]


def _set_terminal_size(master_fd: int, columns: object, rows: object) -> bool:
    if isinstance(columns, bool) or isinstance(rows, bool):
        return False
    try:
        cols = int(columns)
        line_count = int(rows)
    except (TypeError, ValueError):
        return False
    if not 20 <= cols <= 500 or not 5 <= line_count <= 200:
        return False
    packed = struct.pack("HHHH", line_count, cols, 0, 0)
    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, packed)
    return True


def _control_message(value: str) -> dict[str, object] | None:
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    message_type = payload.get("type")
    if message_type not in {"resize", "ping", "terminate"}:
        return None
    return payload


def _terminate_terminal(container_name: str, terminal_id: str) -> None:
    subprocess.run(
        [
            "docker",
            "exec",
            "--user",
            WORKSPACE_USER,
            container_name,
            "tmux",
            "kill-session",
            "-t",
            terminal_id,
        ],
        check=False,
        capture_output=True,
        timeout=10,
    )


async def _read_terminal(master_fd: int, websocket: WebSocket) -> None:
    while True:
        data = await asyncio.to_thread(os.read, master_fd, 8192)
        if not data:
            return
        await websocket.send_bytes(data)


async def _write_terminal(
    master_fd: int,
    websocket: WebSocket,
    workspace_id: str,
    container_name: str,
    terminal_id: str,
) -> None:
    while True:
        message = await websocket.receive()
        if message.get("type") == "websocket.disconnect":
            return

        raw = message.get("bytes")
        if raw is not None:
            if raw:
                await asyncio.to_thread(os.write, master_fd, raw)
                await asyncio.to_thread(_touch_activity, workspace_id)
            continue

        text = message.get("text")
        if text is None:
            continue
        control = _control_message(text)
        if control and control.get("type") == "resize":
            await asyncio.to_thread(
                _set_terminal_size,
                master_fd,
                control.get("cols"),
                control.get("rows"),
            )
            await asyncio.to_thread(_touch_activity, workspace_id)
            continue
        if control and control.get("type") == "ping":
            await asyncio.to_thread(_touch_activity, workspace_id)
            continue
        if control and control.get("type") == "terminate":
            await asyncio.to_thread(
                _terminate_terminal,
                container_name,
                terminal_id,
            )
            return

        encoded = text.encode()
        if encoded:
            await asyncio.to_thread(os.write, master_fd, encoded)
            await asyncio.to_thread(_touch_activity, workspace_id)


async def _terminal_heartbeat(workspace_id: str) -> None:
    interval = max(15, min(60, IDLE_TIMEOUT_SECONDS // 4))
    while True:
        await asyncio.sleep(interval)
        await asyncio.to_thread(_touch_activity, workspace_id)


@app.websocket("/v2/terminal/{workspace_id}")
async def terminal_v2(
    websocket: WebSocket,
    workspace_id: str,
    ticket: str,
) -> None:
    try:
        _verify_origin(websocket)
        verified = _verify_ticket_v2(ticket, workspace_id)
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
    _set_terminal_size(master_fd, 120, 32)
    process = subprocess.Popen(
        _docker_exec_command(container.name, verified),
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
        writer = asyncio.create_task(
            _write_terminal(
                master_fd,
                websocket,
                workspace_id,
                container.name,
                verified.terminal_id,
            )
        )
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
