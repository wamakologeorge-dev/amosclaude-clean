"""Canonical Amosclaud production entry point.

This outer application keeps the complete connected platform active while
exposing the per-user Amosclaud API-key management routes before the mounted
platform catch-all. Both the current ``/api/v1/agent/keys`` path used by the
web dashboard and the compatibility ``/api/v1/autonomous/keys`` path are
available.

Bearer keys are also checked against their selected skills before agent,
Copilot, or VS Code terminal work enters the connected platform. The connected
platform remains responsible for account access, paid usage limits, repository
ownership, approvals, verification, and execution evidence.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, FastAPI, Request

from amoscloud_ai.api.routes import autonomous_keys, owner_access_gateway
from amoscloud_ai.connected_app import app as connected_platform
from amoscloud_ai.copilot import build_copilot_plan

ASGIApp = Callable[
    [dict[str, Any], Callable[..., Awaitable[Any]], Callable[..., Awaitable[Any]]],
    Awaitable[None],
]


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    """Run the complete connected-platform lifecycle exactly once."""

    async with connected_platform.router.lifespan_context(connected_platform):
        yield


def _bearer_token(headers: list[tuple[bytes, bytes]]) -> str:
    for raw_name, raw_value in headers:
        if raw_name.lower() != b"authorization":
            continue
        authorization = raw_value.decode("latin-1").strip()
        scheme, separator, value = authorization.partition(" ")
        if separator and scheme.lower() == "bearer" and value.strip():
            return value.strip()
    return ""


def _mode_skills(mode: str, objective: str = "") -> set[str]:
    normalized = mode.strip().lower()
    text = objective.strip().lower()
    if normalized == "autonomous-check":
        return {"answer", "inspect"}
    if normalized == "build":
        return (
            {"test", "build"}
            if any(term in text for term in ("test", "verify", "ci"))
            else {"build"}
        )
    if normalized == "fix":
        return (
            {"test", "fix"} if any(term in text for term in ("test", "verify", "ci")) else {"fix"}
        )
    if normalized == "deploy":
        return {"deploy"}
    if normalized == "monitor":
        return {"monitor"}
    return set()


def _required_skills(path: str, method: str, payload: dict[str, Any]) -> set[str]:
    if method == "POST" and path == "/api/v1/copilot/plan":
        return {"plan"}

    if method == "POST" and path == "/api/v1/copilot/run":
        task = str(payload.get("task") or "").strip()
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        try:
            plan = build_copilot_plan(
                task,
                requested_agent=str(payload.get("requested_agent") or "") or None,
                repository=str(context.get("repository") or "") or None,
                branch=str(context.get("branch") or "main"),
                file_path=str(context.get("file_path") or "") or None,
                selection=str(context.get("selection") or "") or None,
                language=str(context.get("language") or "") or None,
                source=str(context.get("source") or "") or "amosclaud-copilot",
            )
        except (TypeError, ValueError):
            return set()
        mode = str(plan.get("execution_mode") or "")
        return _mode_skills(mode, task)

    if method == "POST" and path == "/api/v1/agent/run":
        return _mode_skills(
            str(payload.get("mode") or ""),
            str(payload.get("objective") or ""),
        )

    if path == "/api/v1/vscode-terminal/repositories" and method == "GET":
        return {"inspect"}
    if path.startswith("/api/v1/vscode-terminal/repositories/") and method == "POST":
        return {"build"}

    return set()


async def _read_http_messages(
    receive: Callable[..., Awaitable[Any]],
) -> tuple[bytes, Callable[..., Awaitable[Any]]]:
    messages: list[dict[str, Any]] = []
    body_parts: list[bytes] = []
    while True:
        message = await receive()
        messages.append(message)
        if message.get("type") != "http.request":
            break
        body_parts.append(message.get("body", b""))
        if not message.get("more_body", False):
            break

    iterator = iter(messages)

    async def replay() -> dict[str, Any]:
        try:
            return next(iterator)
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}

    return b"".join(body_parts), replay


class ScopedAutonomousKeyASGI:
    """Enforce selected Amosclaud API-key skills before protected tool calls."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[Any]],
        send: Callable[..., Awaitable[Any]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        token = _bearer_token(list(scope.get("headers") or []))
        user = autonomous_keys.authenticate_autonomous_key(token)
        if not user or bool(user["is_admin"]):
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "/")
        method = str(scope.get("method") or "GET").upper()
        body = b""
        replay = receive
        if method in {"POST", "PUT", "PATCH"} and path in {
            "/api/v1/copilot/plan",
            "/api/v1/copilot/run",
            "/api/v1/agent/run",
        }:
            body, replay = await _read_http_messages(receive)

        payload: dict[str, Any] = {}
        if body:
            try:
                decoded = json.loads(body.decode("utf-8"))
                if isinstance(decoded, dict):
                    payload = decoded
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = {}

        required = _required_skills(path, method, payload)
        allowed = autonomous_keys.autonomous_key_skills(user)
        if required and not (required & allowed):
            await self._json_response(
                send,
                403,
                {
                    "detail": "This Amosclaud API key does not allow the requested operation",
                    "required_any": sorted(required),
                    "allowed": sorted(allowed),
                },
            )
            return

        await self.app(scope, replay, send)

    @staticmethod
    async def _json_response(
        send: Callable[..., Awaitable[Any]],
        status: int,
        payload: dict[str, Any],
    ) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        ]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})


agent_key_alias = APIRouter(
    prefix="/api/v1/agent/keys",
    tags=["autonomous-keys"],
)


@agent_key_alias.get("")
def list_agent_keys(request: Request) -> dict:
    """List the signed-in user's Amosclaud API keys."""

    return autonomous_keys.list_keys(request)


@agent_key_alias.post("", status_code=201)
def create_agent_key(
    body: autonomous_keys.KeyCreateRequest,
    request: Request,
) -> dict:
    """Create a scoped Amosclaud API key and display it once."""

    return autonomous_keys.create_key(body, request)


@agent_key_alias.post("/{key_id}/rotate", status_code=201)
def rotate_agent_key(key_id: int, request: Request) -> dict:
    """Rotate one active Amosclaud API key."""

    return autonomous_keys.rotate_key(key_id, request)


@agent_key_alias.delete("/{key_id}", status_code=204)
def revoke_agent_key(key_id: int, request: Request):
    """Revoke one active Amosclaud API key."""

    return autonomous_keys.revoke_key(key_id, request)


app = FastAPI(
    title="Amosclaud Production Platform",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

# Preserve both owner-login route formats before the mounted platform. The
# /api/v1 callback remains compatible with existing GitHub OAuth settings.
app.include_router(owner_access_gateway.router)
app.include_router(owner_access_gateway.router, prefix="/api/v1")

# Compatibility route retained for API clients that already use the original
# autonomous-key path.
app.include_router(autonomous_keys.router, prefix="/api/v1")

# Current dashboard and editor clients use this public key-management path.
app.include_router(agent_key_alias)

# The connected application contains the full platform, paid-tool metering,
# VS Code terminal, legacy MCP, account connector, and owner recovery routes.
# Scoped key checks run before those protected services receive a request.
app.mount(
    "/",
    ScopedAutonomousKeyASGI(connected_platform),
    name="amosclaud-connected-platform",
)


__all__ = ["app"]
