"""Combined Amosclaud platform, GitHub access, paid tools, and remote MCP."""

from __future__ import annotations

import contextlib
import hmac
import json
import os
from collections.abc import Awaitable, Callable
from http.cookies import SimpleCookie
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from amosclaud_mcp.server import mcp as amosclaud_mcp
from amoscloud_ai.api.routes import (
    auth,
    github_access_gateway,
    owner_access_gateway,
    public_developer_tools,
    vscode_terminal,
)
from amoscloud_ai.api.routes.auth import _connect
from amoscloud_ai.main import app as platform_app
from amoscloud_ai.organization_support import (
    api_router as support_api_router,
    bearer_identity,
    debit_support_time,
    page_router as support_page_router,
    payment_required_detail,
    session_identity,
    support_wallet,
    tool_seconds_per_operation,
)

ASGIApp = Callable[
    [dict[str, Any], Callable[..., Awaitable[Any]], Callable[..., Awaitable[Any]]], Awaitable[None]
]

EDITOR_ORIGINS = (
    "https://vscode.dev",
    "https://insiders.vscode.dev",
    "https://github.dev",
)

# GitHub account access, payments, support status, and public source must remain
# reachable before hosted working time exists. Every other official API route is
# treated as a working tool and is charged through the central support wallet.
SUPPORT_EXEMPT_API_PREFIXES = (
    "/api/v1/auth",
    "/api/v1/account",
    "/api/v1/billing",
    "/api/v1/provider/tokens",
    "/api/v1/provider/payments",
    "/api/v1/support-time",
    "/api/v1/open-source",
    "/api/v1/passkey",
    "/api/v1/amos-secure-code",
    "/api/v1/webhooks",
    "/api/v1/service-keys/verify",
)


def expected_mcp_access_key() -> str | None:
    """Return the configured owner MCP key without exposing its value."""

    value = os.getenv("AMOSCLAUD_MCP_ACCESS_KEY") or os.getenv("AMOSCLAUD_AUTONOMOUS_KEY")
    cleaned = (value or "").strip()
    return cleaned or None


def mcp_request_is_authorized(headers: list[tuple[bytes, bytes]], expected: str | None) -> bool:
    """Validate the legacy owner MCP bearer token using constant-time comparison."""

    if not expected:
        return False
    supplied = _bearer_token(headers)
    return bool(supplied) and hmac.compare_digest(supplied, expected)


def _header_value(headers: list[tuple[bytes, bytes]], name: bytes) -> str:
    for raw_name, raw_value in headers:
        if raw_name.lower() == name:
            return raw_value.decode("latin-1").strip()
    return ""


def _bearer_token(headers: list[tuple[bytes, bytes]]) -> str:
    authorization = _header_value(headers, b"authorization")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return ""
    return authorization[len(prefix) :].strip()


def _session_cookie(headers: list[tuple[bytes, bytes]]) -> str | None:
    raw = _header_value(headers, b"cookie")
    if not raw:
        return None
    cookie = SimpleCookie()
    try:
        cookie.load(raw)
    except Exception:
        return None
    morsel = cookie.get("amos_session")
    return morsel.value if morsel else None


def _is_hosted_tool_path(path: str) -> bool:
    if path.startswith("/v1/"):
        return True
    if not path.startswith("/api/v1/"):
        return False
    return not any(path.startswith(prefix) for prefix in SUPPORT_EXEMPT_API_PREFIXES)


class HostedToolSupportASGI:
    """Require verified support time before official hosted tools can execute."""

    def __init__(self, app: ASGIApp, *, all_requests: bool = False) -> None:
        self.app = app
        self.all_requests = all_requests

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[Any]],
        send: Callable[..., Awaitable[Any]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        method = str(scope.get("method") or "GET").upper()
        path = str(scope.get("path") or "/")
        if method == "OPTIONS" or (not self.all_requests and not _is_hosted_tool_path(path)):
            await self.app(scope, receive, send)
            return

        headers = list(scope.get("headers") or [])
        raw_bearer = _bearer_token(headers)
        identity = bearer_identity(raw_bearer) if raw_bearer else None
        if identity is None:
            identity = session_identity(_session_cookie(headers))
        if identity is None:
            await self._json_response(
                send,
                401,
                {"detail": "Sign in with GitHub or provide a valid Amosclaud API key"},
                extra_headers=[(b"www-authenticate", b"Bearer")],
            )
            return

        required_seconds = tool_seconds_per_operation()
        remaining: int | None = None
        if not bool(identity["is_admin"]):
            with _connect() as db:
                remaining = support_wallet(db, int(identity["user_id"]))["remaining_seconds"]
            if remaining < required_seconds:
                await self._json_response(send, 402, {"detail": payment_required_detail()})
                return

        charged = False

        async def send_with_support_header(message: dict[str, Any]) -> None:
            nonlocal charged, remaining
            if message.get("type") == "http.response.start" and remaining is not None:
                status = int(message.get("status") or 500)
                if not charged and status < 400:
                    with _connect() as db:
                        did_charge, remaining = debit_support_time(
                            db,
                            int(identity["user_id"]),
                            required_seconds,
                        )
                    charged = did_charge
                response_headers = list(message.get("headers") or [])
                response_headers.append(
                    (b"x-amosclaud-support-seconds-remaining", str(remaining).encode("ascii"))
                )
                message = {**message, "headers": response_headers}
            await send(message)

        await self.app(scope, receive, send_with_support_header)

    @staticmethod
    async def _json_response(
        send: Callable[..., Awaitable[Any]],
        status: int,
        payload: dict[str, Any],
        *,
        extra_headers: list[tuple[bytes, bytes]] | None = None,
    ) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        ]
        headers.extend(extra_headers or [])
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})


class BearerProtectedASGI(HostedToolSupportASGI):
    """Compatibility name for the remote MCP paid-support gateway."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app, all_requests=True)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    """Run both the platform and MCP lifecycle managers."""

    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(platform_app.router.lifespan_context(platform_app))
        await stack.enter_async_context(amosclaud_mcp.session_manager.run())
        yield


# The production combined application is also the browser-editor gateway.
platform_app.include_router(vscode_terminal.router, prefix="/api/v1")

app = FastAPI(
    title="Amosclaud Platform and MCP",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(EDITOR_ORIGINS),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Mcp-Session-Id", "MCP-Protocol-Version"],
    expose_headers=["Mcp-Session-Id", "X-Amosclaud-Support-Seconds-Remaining"],
)

# Public source and organization support pages remain reachable without a
# session. The old password page is replaced by the GitHub OAuth redirect.
app.include_router(public_developer_tools.router)
app.include_router(support_page_router)
app.include_router(support_api_router, prefix="/api/v1")
app.include_router(github_access_gateway.router)
app.include_router(github_access_gateway.router, prefix="/api/v1")

# Keep the separate owner-recovery callback, but register it after GitHub-only
# access so its legacy email registration endpoint cannot become public again.
app.include_router(owner_access_gateway.router)

amosclaud_mcp.settings.streamable_http_path = "/"
app.mount("/mcp", BearerProtectedASGI(amosclaud_mcp.streamable_http_app()), name="amosclaud-mcp")
app.mount("/", HostedToolSupportASGI(platform_app), name="amosclaud-platform")
