"""Provider-independent Amosclaud production entry point.

This application places the Amosclaud-first production API before the existing
platform catch-all. It can be used by a self-hosted server or a compatible
serverless/front-door provider without making Railway or GitHub CI authoritative.
"""

from __future__ import annotations

import contextlib

from fastapi import FastAPI

from amoscloud_ai.api.routes.amosclaud_production import router as production_router
from amoscloud_ai.production_app import app as connected_production_app


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    async with connected_production_app.router.lifespan_context(connected_production_app):
        yield


app = FastAPI(
    title="Amosclaud First Production",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.include_router(production_router, prefix="/api/v1")
app.mount("/", connected_production_app, name="amosclaud-connected-production")


__all__ = ["app"]
