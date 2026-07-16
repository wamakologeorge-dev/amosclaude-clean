"""Fast liveness and detailed autonomous-readiness routes."""

from datetime import datetime, timezone

from fastapi import APIRouter

from amoscloud_ai import provider
from amoscloud_ai.api.routes import (
    control_bus_dashboard,
    mapping_bundles,
    model_server_folder,
    openai_compat,
)
from amoscloud_ai.config import settings
from amoscloud_ai.models import HealthResponse
from amoscloud_ai.server.cb import router as amosclaud_cb_router

router = APIRouter(tags=["health"])
router.include_router(model_server_folder.router, prefix="/api/v1")
router.include_router(openai_compat.router)
router.include_router(mapping_bundles.api_router, prefix="/api/v1")
router.include_router(mapping_bundles.dashboard_router)
router.include_router(control_bus_dashboard.router)
router.include_router(amosclaud_cb_router, prefix="/api/v1")

from amoscloud_ai.api.routes import codex_system_bundle
router.include_router(codex_system_bundle.router, prefix="/api/v1")


@router.get("/health", response_model=HealthResponse, summary="Service liveness check")
async def health() -> HealthResponse:
    """Return quickly when the web process is alive.

    Railway should use this endpoint. Optional model and worker dependencies are
    intentionally excluded so they cannot make the web service fail liveness.
    """
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        environment=settings.environment,
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/ready", summary="Autonomous service readiness")
async def readiness() -> dict[str, object]:
    """Return a safe component summary without exposing keys or endpoint URLs."""
    state = provider.status()
    network = state.get("model_network", {})
    configured = bool(
        network.get("ready")
        or state.get("self_hosted_configured")
        or state.get("amosclaud_api_configured")
        or (
            state.get("external_adapters_enabled")
            and (state.get("openai_configured") or state.get("anthropic_configured"))
        )
    )
    return {
        "status": "ready" if configured else "degraded",
        "web": {"ready": True},
        "autonomous_api": {
            "ready": True,
            "route": "/api/v1/agent/run",
            "result_route": "/api/v1/pipelines/{pipeline_id}",
            "authentication": ["session", "Authorization: Bearer <autonomous-key>"],
        },
        "provider": state,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
