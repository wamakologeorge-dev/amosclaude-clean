"""Amosclaud AI – FastAPI application entry point.

Run directly:
    python -m amoscloud_ai.main

Or with uvicorn:
    uvicorn amoscloud_ai.main:app --host 0.0.0.0 --port 8000
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from amoscloud_ai import __version__
from amoscloud_ai.api.routes import agent, auth, chat, copilot, deployments, feed, health, pipelines, pr_tasks, repositories
from amoscloud_ai.api.routes.auth import DB_PATH, get_user_from_session
from amoscloud_ai.config import settings
from amoscloud_ai.logger import log


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    repositories.REPOSITORY_ROOT.mkdir(parents=True, exist_ok=True)
    log.info(f"🚀 {settings.app_name} v{__version__} starting [{settings.environment}] on {settings.host}:{settings.port}")
    yield
    log.info("Shutting down Amosclaud AI server")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Self-hosted CI/CD, deployment automation, authentication, and native repository hosting.",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_hosts,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(auth.router, include_in_schema=False)
    app.include_router(agent.router, prefix="/api/v1")
    app.include_router(copilot.router, prefix="/api/v1")
    app.include_router(pr_tasks.router, prefix="/api/v1")
    app.include_router(pipelines.router, prefix="/api/v1")
    app.include_router(deployments.router, prefix="/api/v1")
    app.include_router(repositories.router, prefix="/api/v1")
    app.include_router(feed.router, prefix="/api/v1")

    web_dir = Path(__file__).resolve().parent.parent / "web"
    if web_dir.exists():
        app.mount("/static", StaticFiles(directory=web_dir), name="static")

    @app.get("/feed", include_in_schema=False)
    async def public_feed():
        return FileResponse(web_dir / "feed.html")

    @app.get("/login", include_in_schema=False)
    async def login_page(request: Request):
        if get_user_from_session(request.cookies.get("amos_session")):
            return RedirectResponse("/", status_code=302)
        return FileResponse(web_dir / "login.html")

    @app.get("/repositories", include_in_schema=False)
    async def repositories_page(request: Request):
        if not get_user_from_session(request.cookies.get("amos_session")):
            return RedirectResponse("/login", status_code=302)
        return FileResponse(web_dir / "repositories.html")

    @app.get("/workspace/{repository_id}", include_in_schema=False)
    async def repository_workspace(repository_id: int, request: Request):
        if not get_user_from_session(request.cookies.get("amos_session")):
            return RedirectResponse("/login", status_code=302)
        return FileResponse(web_dir / "workspace.html")

    @app.get("/", include_in_schema=False)
    async def dashboard(request: Request):
        if not get_user_from_session(request.cookies.get("amos_session")):
            return RedirectResponse("/login", status_code=302)
        return FileResponse(web_dir / "index.html")

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
