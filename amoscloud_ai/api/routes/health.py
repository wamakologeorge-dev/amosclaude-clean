"""Fast liveness and detailed autonomous-readiness routes."""

from datetime import datetime, timezone

from fastapi import APIRouter

from amoscloud_ai import provider
from amoscloud_ai.api.routes import bundle_pages, bundles, codex_system_bundle
from amoscloud_ai.config import settings
from amoscloud_ai.models import HealthResponse

router = APIRouter(tags=["health"])
router.include_router(bundles.router, prefix="/api/v1")
router.include_router(bundle_pages.router)
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
