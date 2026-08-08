"""Canonical Amosclaud production entry point.

This outer application keeps the complete connected platform active while
exposing the per-user Amosclaud API-key management routes before the mounted
platform catch-all.  Both the current ``/api/v1/agent/keys`` path used by the
web dashboard and the compatibility ``/api/v1/autonomous/keys`` path are
available.
"""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, FastAPI, Request

from amoscloud_ai.api.routes import autonomous_keys
from amoscloud_ai.connected_app import app as connected_platform


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    """Run the complete connected-platform lifecycle exactly once."""

    async with connected_platform.router.lifespan_context(connected_platform):
        yield


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

# Compatibility route retained for API clients that already use the original
# autonomous-key path.
app.include_router(autonomous_keys.router, prefix="/api/v1")

# Current dashboard and editor clients use this public key-management path.
app.include_router(agent_key_alias)

# The connected application contains the full platform, paid-tool metering,
# VS Code terminal, legacy MCP, account connector, and owner recovery routes.
app.mount("/", connected_platform, name="amosclaud-connected-platform")


__all__ = ["app"]
