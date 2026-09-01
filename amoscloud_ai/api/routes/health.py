"""Fast liveness, readiness, and direct critical-platform routes."""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Header, Request
from fastapi.responses import FileResponse, RedirectResponse

from amomodel.api import router as amomodel_router
from amomodel.api import status as amomodel_status
from amoscloud_ai import provider
from amoscloud_ai.agent.preflight import run_preflight
from amoscloud_ai.api.routes import (
    amosclaud_authority,
    autonomous_codex,
    book,
    bundle_pages,
    bundles,
    cdn,
    codex_system_bundle,
    control_bus_dashboard,
    github_repository_management,
    industrial_autonomy,
    metadata_dashboard,
    monitoring,
    native_issue_timeline,
    openai_compat,
    owner_bootstrap,
)
from amoscloud_ai.api.routes.auth import get_user_from_session
from amoscloud_ai.autonomous.server.api.cb.router.byte.metadata import (
    router as byte_metadata_router,
)
from amoscloud_ai.config import settings
from amoscloud_ai.deployment_health import status as deployment_health_status
from amoscloud_ai.models import HealthResponse
from amoscloud_ai.server.cb.Amosclaud import server_identity

router = APIRouter(tags=["health"])
WEB_DIR = Path(__file__).resolve().parents[3] / "web"

# Register this before the normal auth router so a brand-new installation can
# create its configured owner account even before outbound email is available.
router.include_router(owner_bootstrap.router, prefix="/api/v1")

# These service routers are composed here so the platform always exposes its
# critical Autonomous contracts even when a deployment imports only health.
router.include_router(amosclaud_authority.router, prefix="/api/v1")
router.include_router(book.router, prefix="/api/v1")
router.include_router(bundles.router, prefix="/api/v1")
router.include_router(bundle_pages.router)
router.include_router(byte_metadata_router, prefix="/api/v1")
router.include_router(codex_system_bundle.router, prefix="/api/v1")
router.include_router(autonomous_codex.router, prefix="/api/v1")
router.include_router(industrial_autonomy.router, prefix="/api/v1")
router.include_router(github_repository_management.router, prefix="/api/v1")
router.include_router(amomodel_router, prefix="/api/v1")
router.include_router(monitoring.router, prefix="/api/v1")
router.include_router(cdn.router, prefix="/api/v1")
router.include_router(native_issue_timeline.router, prefix="/api/v1")


@router.get("/book", include_in_schema=False)
async def public_word_book() -> FileResponse:
    """Serve the public Amosclaud living manual and developer Book."""
    return FileResponse(WEB_DIR / "amosclaud-book.html")


@router.get("/slapface", include_in_schema=False)
async def public_slapface_intro() -> RedirectResponse:
    """Open Chapter 00, the public Slapface introduction to the Book."""
    return RedirectResponse("/book?chapter=00#slapface", status_code=302)


@router.get("/status", include_in_schema=False)
async def public_status_page() -> FileResponse:
    """Serve a public, read-only view of safe platform health information."""
    return FileResponse(WEB_DIR / "status.html")


@router.get("/support", include_in_schema=False)
async def public_support_page() -> FileResponse:
    """Serve the public, read-only Amosclaud contribution policy and payment link."""
    return FileResponse(WEB_DIR / "support.html")


@router.get("/organization-access", include_in_schema=False)
async def public_organization_access_page() -> RedirectResponse:
    """Keep the legacy URL while using the single account portal."""
    return RedirectResponse("/login?method=organization", status_code=302)


@router.get("/account", include_in_schema=False)
async def account_page(request: Request):
    """Serve self-service account controls to an authenticated user."""
    if not get_user_from_session(request.cookies.get("amos_session")):
        return RedirectResponse("/login", status_code=302)
    return FileResponse(WEB_DIR / "account.html")


@router.get("/autonomous-codex-configuration", include_in_schema=False)
async def autonomous_codex_dashboard(request: Request):
    if not get_user_from_session(request.cookies.get("amos_session")):
        return RedirectResponse("/login", status_code=302)
    return FileResponse(WEB_DIR / "autonomous-codex.html")


@router.get("/health", response_model=HealthResponse, summary="Service liveness check")
async def health() -> HealthResponse:
    """Return quickly when the web process is alive."""
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        environment=settings.environment,
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/api/v1/public/status", summary="Public Amosclaud platform status")
async def public_platform_status() -> dict[str, object]:
    """Return a redacted status summary that never exposes accounts or secrets."""
    state = provider.status()
    runtime = state.get("model_runtime")
    runtime = runtime if isinstance(runtime, dict) else {}
    network = state.get("model_network")
    network = network if isinstance(network, dict) else {}

    model_configured = bool(
        network.get("ready")
        or state.get("self_hosted_configured")
        or state.get("amosclaud_api_configured")
        or (
            state.get("external_adapters_enabled")
            and (state.get("openai_configured") or state.get("anthropic_configured"))
        )
    )
    runtime_reachable = runtime.get("reachable")
    if runtime_reachable is True:
        runtime_state = "operational"
        runtime_summary = "A configured model route answered its bounded health check."
    elif model_configured:
        runtime_state = "degraded"
        runtime_summary = "A model route is configured but is not currently reachable."
    else:
        runtime_state = "not_configured"
        runtime_summary = "No model route is configured for this deployment."

    network_ready = bool(network.get("ready"))
    components = [
        {
            "id": "web",
            "name": "Web application",
            "state": "operational",
            "summary": "The Amosclaud web process served this status response.",
        },
        {
            "id": "autonomous-api",
            "name": "Autonomous task API",
            "state": "operational",
            "summary": "The platform route for authenticated agent tasks is registered.",
        },
        {
            "id": "model-runtime",
            "name": "Model runtime",
            "state": runtime_state,
            "summary": runtime_summary,
        },
        {
            "id": "model-network",
            "name": "Model station network",
            "state": "operational" if network_ready else "not_configured",
            "summary": (
                "At least one first-party model station is ready."
                if network_ready
                else "No ready first-party model station is currently reported."
            ),
        },
    ]
    overall = (
        "operational"
        if all(component["state"] == "operational" for component in components)
        else "degraded"
    )
    return {
        "product": "Amosclaud",
        "status": overall,
        "version": settings.app_version,
        "environment": settings.environment,
        "components": components,
        "source_repository": "wamakologeorge-dev/amosclaude-clean",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


# The remaining existing health/readiness routes continue below this section.
