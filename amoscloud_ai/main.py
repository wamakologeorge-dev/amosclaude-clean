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
from dotenv import load_dotenv

load_dotenv()
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from amoscloud_ai import __version__, model_network
from amoscloud_ai.api.routes import (
    account,
    account_recovery,
    academy,
    admin,
    agent,
    agent_buddies,
    agent_chain,
    agent_readiness,
    amo_runtime,
    amo_tokens,
    amos_mail,
    amos_secure_code,
    auth,
    billing,
    bundles_api_host,
    chat,
    community,
    copilot,
    core,
    deployments,
    downloads,
    doctor_medical,
    doctor_travel,
    feed,
    first_party_chat,
    github_repositories,
    github_travel,
    health,
    local_workspace,
    mapping_bundles,
    model_server_folder,
    metadata_dashboard,
    organizations,
    operation_buckets,
    openai_compat,
    passkey_signup,
    pipelines,
    provider_api,
    pr_tasks,
    repositories,
    repository_templates,
    reviews,
    server_stations,
    service_keys,
    storage,
    task_router,
    wifi,
    webhooks,
    workspaces,
    control_bus_dashboard,
)
from amoscloud_ai.api.routes.auth import DB_PATH, get_user_from_session
from amoscloud_ai.config import settings
from amoscloud_ai.core.workspace import WorkspaceEngine
from amoscloud_ai.server.cb import router as amosclaud_cb_router
from amoscloud_ai.db_migrations import run_migrations
from amoscloud_ai.logger import log
from amoscloud_ai.security import SecurityMiddleware
from amosclaud_metrics.integration import install_metrics


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with auth._connect():
        pass
    run_migrations(DB_PATH)
    repositories.REPOSITORY_ROOT.mkdir(parents=True, exist_ok=True)
    storage.STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    WorkspaceEngine()
    log.info(
        f"🚀 {settings.app_name} v{__version__} starting "
        f"[{settings.environment}] on {settings.host}:{settings.port}"
    )
    yield
    log.info("Shutting down Amosclaud AI server")


def create_app() -> FastAPI:
    production = settings.environment.lower() in {"production", "prod"}
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Folder-first, self-hosted Amosclaud platform for local AI, "
            "repositories, projects, tasks, knowledge, storage, and automation."
        ),
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        lifespan=lifespan,
    )
    app.add_middleware(SecurityMiddleware)
    install_metrics(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_hosts,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "Authorization",
            "X-API-Key",
            "X-Amosclaud-Owner-Key",
        ],
    )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        log.exception(
            "Unhandled request failure on %s %s",
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": (
                    "Amosclaud could not complete this request. "
                    "The error was recorded in the server logs."
                ),
                "error": "internal_server_error",
                "path": request.url.path,
            },
        )

    @app.middleware("http")
    async def block_suspended_accounts(request: Request, call_next):
        token = request.cookies.get("amos_session")
        if token and admin.is_session_suspended(token):
            response = JSONResponse(
                {"detail": "This account is suspended"},
                status_code=403,
            )
            response.delete_cookie("amos_session", path="/")
            return response
        return await call_next(request)

    app.include_router(health.router)
    # Mount service routers directly on the application. New FastAPI releases
    # preserve nested APIRouters as wrapper entries, which made these endpoints
    # invisible to route discovery and prevented agent tools from executing.
    app.include_router(model_server_folder.router, prefix="/api/v1")
    app.include_router(openai_compat.router)
    app.include_router(mapping_bundles.api_router, prefix="/api/v1")
    app.include_router(mapping_bundles.dashboard_router)
    app.include_router(control_bus_dashboard.router)
    app.include_router(amosclaud_cb_router, prefix="/api/v1")
    app.include_router(first_party_chat.router)
    app.include_router(chat.router, include_in_schema=False)
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(auth.router, include_in_schema=False)
    app.include_router(account_recovery.router, prefix="/api/v1/auth")
    app.include_router(billing.router, prefix="/api/v1")
    app.include_router(bundles_api_host.router, prefix="/api/v1")
    app.include_router(provider_api.router, prefix="/api/v1")
    app.include_router(account.router, prefix="/api/v1")
    app.include_router(account_recovery.router, prefix="/api/v1/auth")
    app.include_router(amos_secure_code.router, prefix="/api/v1")
    app.include_router(passkey_signup.router, prefix="/api/v1")
    app.include_router(agent_chain.router, prefix="/api/v1")
    app.include_router(metadata_dashboard.router, prefix="/api/v1/agent-chain")
    app.include_router(agent.router, prefix="/api/v1")
    app.include_router(agent_buddies.router, prefix="/api/v1")
    app.include_router(agent_readiness.router, prefix="/api/v1")
    app.include_router(amo_runtime.router, prefix="/api/v1")
    app.include_router(copilot.router, prefix="/api/v1")
    app.include_router(pr_tasks.router, prefix="/api/v1")
    app.include_router(github_travel.router, prefix="/api/v1")
    app.include_router(pipelines.router, prefix="/api/v1")
    app.include_router(reviews.router, prefix="/api/v1")
    app.include_router(deployments.router, prefix="/api/v1")
    app.include_router(downloads.router, prefix="/api/v1")
    app.include_router(repositories.router, prefix="/api/v1")
    app.include_router(github_repositories.router, prefix="/api/v1")
    app.include_router(repository_templates.router, prefix="/api/v1")
    app.include_router(organizations.router, prefix="/api/v1")
    app.include_router(operation_buckets.router, prefix="/api/v1")
    app.include_router(workspaces.router, prefix="/api/v1")
    app.include_router(local_workspace.router, prefix="/api/v1")
    app.include_router(storage.router, prefix="/api/v1")
    app.include_router(task_router.router, prefix="/api/v1")
    app.include_router(server_stations.router, prefix="/api/v1")
    app.include_router(service_keys.admin_router, prefix="/api/v1")
    app.include_router(service_keys.verify_router, prefix="/api/v1")
    app.include_router(model_network.router, prefix="/api/v1")
    app.include_router(community.router, prefix="/api/v1")
    app.include_router(feed.router, prefix="/api/v1")
    app.include_router(amos_mail.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")
    app.include_router(doctor_medical.router, prefix="/api/v1")
    app.include_router(doctor_travel.router, prefix="/api/v1")
    app.include_router(core.router, prefix="/api/v1")
    app.include_router(academy.router, prefix="/api/v1")
    app.include_router(amo_tokens.router, prefix="/api/v1")
    app.include_router(wifi.router, prefix="/api/v1")
    app.include_router(webhooks.router, prefix="/api/v1")

    web_dir = Path(__file__).resolve().parent.parent / "web"
    project_dir = web_dir.parent
    if web_dir.exists():
        app.mount("/static", StaticFiles(directory=web_dir), name="static")

    hub_dir = project_dir / "pages-site"
    if hub_dir.exists():
        app.mount(
            "/hub",
            StaticFiles(directory=hub_dir, html=True),
            name="hub",
        )

    @app.get("/service-worker.js", include_in_schema=False)
    async def service_worker():
        return FileResponse(
            web_dir / "service-worker.js",
            media_type="application/javascript",
            headers={
                "Service-Worker-Allowed": "/",
                "Cache-Control": "no-cache",
            },
        )

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def web_manifest():
        return FileResponse(
            web_dir / "manifest.webmanifest",
            media_type="application/manifest+json",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/.well-known/ai-plugin.json", include_in_schema=False)
    async def ai_plugin_manifest():
        return FileResponse(
            web_dir / "ai-plugin.json",
            media_type="application/json",
        )

    @app.get("/openapi.yaml", include_in_schema=False)
    async def developer_openapi_contract():
        return FileResponse(
            project_dir / "openapi.yaml",
            media_type="application/yaml",
        )

    @app.get("/api-access", include_in_schema=False)
    async def api_access_page():
        return FileResponse(web_dir / "api-access.html")

    @app.get("/tasks", include_in_schema=False)
    async def tasks_page():
        return FileResponse(web_dir / "tasks.html")

    @app.get("/plans", include_in_schema=False)
    async def plans_page():
        return FileResponse(web_dir / "plans.html")

    @app.get("/download", include_in_schema=False)
    async def download_page():
        return FileResponse(web_dir / "download.html")

    @app.get("/feed", include_in_schema=False)
    async def public_feed():
        return FileResponse(web_dir / "feed.html")

    @app.get("/community", include_in_schema=False)
    async def community_page(request: Request):
        if not get_user_from_session(request.cookies.get("amos_session")):
            return RedirectResponse("/login", status_code=302)
        return FileResponse(web_dir / "community.html")

    @app.get("/login", include_in_schema=False)
    async def login_page(request: Request):
        if get_user_from_session(request.cookies.get("amos_session")):
            return RedirectResponse("/cloud/agent", status_code=302)
        return FileResponse(web_dir / "login.html")

    @app.get("/repositories", include_in_schema=False)
    async def repositories_page(request: Request):
        if not get_user_from_session(request.cookies.get("amos_session")):
            return RedirectResponse("/login", status_code=302)
        return FileResponse(web_dir / "repositories.html")

    @app.get("/admin", include_in_schema=False)
    async def admin_page(request: Request):
        user = get_user_from_session(request.cookies.get("amos_session"))
        if not user:
            return RedirectResponse("/login", status_code=302)
        if not bool(user["is_admin"]):
            return RedirectResponse("/cloud/agent", status_code=302)
        return FileResponse(web_dir / "admin.html")

    @app.get("/admin/academy", include_in_schema=False)
    async def academy_dashboard_page(request: Request):
        user = get_user_from_session(request.cookies.get("amos_session"))
        if not user:
            return RedirectResponse("/login", status_code=302)
        if not bool(user["is_admin"]):
            return RedirectResponse("/cloud/agent", status_code=302)
        return FileResponse(web_dir / "academy-dashboard.html")

    @app.get("/admin/wifi", include_in_schema=False)
    async def wifi_admin_page(request: Request):
        user = get_user_from_session(request.cookies.get("amos_session"))
        if not user:
            return RedirectResponse("/login", status_code=302)
        if not bool(user["is_admin"]):
            return RedirectResponse("/cloud/agent", status_code=302)
        return FileResponse(web_dir / "wifi.html")

    @app.get("/admin/bundles", include_in_schema=False)
    async def bundles_api_docs_page(request: Request):
        user = get_user_from_session(request.cookies.get("amos_session"))
        if not user:
            return RedirectResponse("/login", status_code=302)
        if not bool(user["is_admin"]):
            return RedirectResponse("/cloud/agent", status_code=302)
        return FileResponse(web_dir / "bundles-api-docs.html")

    @app.get("/admin/service-keys", include_in_schema=False)
    async def service_key_control_panel(request: Request):
        user = get_user_from_session(request.cookies.get("amos_session"))
        if not user:
            return RedirectResponse("/login", status_code=302)
        if not bool(user["is_admin"]):
            return RedirectResponse("/cloud/agent", status_code=302)
        return FileResponse(web_dir / "service-key-control-panel.html")

    @app.get("/mail", include_in_schema=False)
    async def mail_page(request: Request):
        if not get_user_from_session(request.cookies.get("amos_session")):
            return RedirectResponse("/login", status_code=302)
        return FileResponse(web_dir / "mail.html")

    @app.get("/workspace/{repository_id}", include_in_schema=False)
    async def repository_workspace(repository_id: int, request: Request):
        if not get_user_from_session(request.cookies.get("amos_session")):
            return RedirectResponse("/login", status_code=302)
        return FileResponse(web_dir / "workspace.html")

    @app.get("/cloud/agent", include_in_schema=False)
    async def cloud_agent_page(request: Request):
        if not get_user_from_session(request.cookies.get("amos_session")):
            return RedirectResponse("/login", status_code=302)
        return FileResponse(web_dir / "index.html")

    @app.get("/autonomous", include_in_schema=False)
    async def autonomous_legacy_route(request: Request):
        if not get_user_from_session(request.cookies.get("amos_session")):
            return RedirectResponse("/login", status_code=302)
        return RedirectResponse("/cloud/agent", status_code=308)

    @app.get("/", include_in_schema=False)
    async def dashboard(request: Request):
        if not get_user_from_session(request.cookies.get("amos_session")):
            return RedirectResponse("/login", status_code=302)
        return RedirectResponse("/cloud/agent", status_code=302)

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "amoscloud_ai.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.environment == "development",
    )
