"""Standalone application entry point for the Amosclaud Bundles API Host."""

from fastapi import FastAPI

from amoscloud_ai.api.routes.bundles_api_host import router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Amosclaud Bundles API Host",
        version="1.0.0",
        description="Authenticated, checksum-verified Amosclaud software bundle registry.",
    )
    app.include_router(router, prefix="/api/v1")
    return app


app = create_app()
