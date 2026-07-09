"""Amosclaud AI – FastAPI application entry point.

Run directly:
    python -m amoscloud_ai.main

Or with uvicorn:
    uvicorn amoscloud_ai.main:app --host 0.0.0.0 --port 8000
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from amoscloud_ai import __version__
from amoscloud_ai.api.routes import agent, deployments, health, pipelines
from amoscloud_ai.config import settings
from amoscloud_ai.logger import log


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    log.info(
        f"🚀 {settings.app_name} v{__version__} starting "
        f"[{settings.environment}] on {settings.host}:{settings.port}"
    )
    yield
    log.info("Shutting down Amosclaud AI server")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Self-hosted CI/CD & Deployment Automation server. "
            "Manage pipelines, deployments, and database migrations via REST API."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_hosts,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(health.router)
    app.include_router(agent.router, prefix="/api/v1")
    app.include_router(pipelines.router, prefix="/api/v1")
    app.include_router(deployments.router, prefix="/api/v1")

    # Mount web dashboard static files
    web_dir = os.path.join(os.path.dirname(__file__), "..", "web")
    if os.path.exists(web_dir):
        app.mount("/static", StaticFiles(directory=web_dir), name="static")

    @app.get("/", include_in_schema=False)
    async def dashboard() -> FileResponse:
        index_path = os.path.join(os.path.dirname(__file__), "..", "web", "index.html")
        return FileResponse(index_path)

    return app


app = create_app()


def main() -> None:
    uvicorn.run(
        "amoscloud_ai.main:app",
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
