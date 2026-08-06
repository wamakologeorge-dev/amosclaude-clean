"""Combined Amosclaud platform and authenticated remote MCP application.

The normal FastAPI platform remains mounted at the root. The first-party MCP
server is exposed at ``/mcp`` over Streamable HTTP so browser-based VS Code,
GitHub Codespaces, and other remote MCP clients can use Amosclaud tools.
"""

from __future__ import annotations

import contextlib
import hmac
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from amosclaud_mcp.server import mcp as amosclaud_mcp
from amoscloud_ai.api.routes import auth, owner_access_gateway, vscode_terminal
from amoscloud_ai.auth_mail_bridge import install_auth_mail_delivery
from amoscloud_ai.main import app as platform_app

ASGIApp = Callable[
    [dict[str, Any], Callable[..., Awaitable[Any]], Callable[..., Awaitable[Any]]], Awaitable[None]
]

EDITOR_ORIGINS = (
    "https://vscode.dev",
    "https://insiders.vscode.dev",
    "https://github.dev",
)

# The production application historically used an older SMTP-only sender inside
# the account router. Replace that private hook before the first request so
# registration, email-code login, and password recovery all use the central
# HTTPS-or-SMTP mail transport.
install_auth_mail_delivery(auth)


def expected_mcp_access_key() -> str | None:
    """Return the configured remote MCP access key without exposing its value."""

    value = os.getenv("AMOSCLAUD_MCP_ACCESS_KEY") or os.getenv("AMOSCLAUD_AUTONOMOUS_KEY")
    cleaned = (value or "").strip()
    return cleaned or None


def mcp_request_is_authorized(headers: list[tuple[bytes, bytes]], expected: str | None) -> bool:
    """Validate an MCP bearer token using constant-time comparison."""

    if not expected:
        return False
    authorization = ""
    for raw_name, raw_value in headers:
        if raw_name.lower() == b"authorization":
            authorization = raw_value.decode("latin-1").strip()
            break
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return False
    supplied = authorization[len(prefix) :].strip()
    return bool(supplied) and hmac.compare_digest(supplied, expected)


class BearerProtectedASGI:
    """Require a configured bearer key before any remote MCP protocol traffic."""

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

        expected = expected_mcp_access_key()
        if not expected:
            await self._json_response(
                send,
                503,
                {"detail": "Remote Amosclaud MCP is not configured"},
            )
            return
        if not mcp_request_is_authorized(scope.get("headers", []), expected):
            await self._json_response(
                send,
                401,
                {"detail": "A valid Amosclaud MCP bearer key is required"},
                extra_headers=[(b"www-authenticate", b"Bearer")],
            )
            return
        await self.app(scope, receive, send)

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


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    """Run both the platform and MCP lifecycle managers."""

    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(platform_app.router.lifespan_context(platform_app))
        await stack.enter_async_context(amosclaud_mcp.session_manager.run())
        yield


# The production combined application is also the browser-editor gateway.
# Mount this router directly so the same deployment serves Chat, MCP, and each
# user's repository-scoped terminal without a second public service.
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
    expose_headers=["Mcp-Session-Id"],
)

# These owner routes must be registered before the catch-all platform mount.
# They preserve normal email verification and add only a bounded first-owner
# fallback plus the existing GitHub-verified owner recovery flow.
app.include_router(owner_access_gateway.router)

amosclaud_mcp.settings.streamable_http_path = "/"
app.mount("/mcp", BearerProtectedASGI(amosclaud_mcp.streamable_http_app()), name="amosclaud-mcp")
app.mount("/", platform_app, name="amosclaud-platform")
