"""Production entry point with the legacy platform and the account connector."""

from __future__ import annotations

import contextlib

from fastapi import FastAPI

from amoscloud_ai.combined_app import app as platform_app
from amoscloud_ai.connectors.amosclaud_account.oauth import router as connector_oauth_router
from amoscloud_ai.connectors.amosclaud_account.server import mcp as account_mcp


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    """Run the existing platform plus the dedicated account MCP lifecycle."""

    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(platform_app.router.lifespan_context(platform_app))
        await stack.enter_async_context(account_mcp.session_manager.run())
        yield


app = FastAPI(
    title="Amosclaud Platform with Account Connector",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

# OAuth discovery and account authorization must be reachable before the
# catch-all platform mount.
app.include_router(connector_oauth_router)

account_mcp.settings.streamable_http_path = "/"
app.mount(
    "/connectors/amosclaud/v1/mcp",
    account_mcp.streamable_http_app(),
    name="amosclaud-account-connector",
)

# Preserve every existing Amosclaud route and the older owner-key /mcp endpoint.
app.mount("/", platform_app, name="amosclaud-platform")
