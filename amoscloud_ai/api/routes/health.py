"""Fast liveness, readiness, and direct critical-platform routes."""

from datetime import datetime, timezone

from fastapi import APIRouter, Header, Request

from amomodel.api import status as amomodel_status
from amoscloud_ai import provider
from amoscloud_ai.api.routes import (
    bundle_pages,
    bundles,
    control_bus_dashboard,
    metadata_dashboard,
    openai_compat,
)
from amoscloud_ai.config import settings
from amoscloud_ai.models import HealthResponse
from amoscloud_ai.server.cb.Amosclaud import server_identity

router = APIRouter(tags=["health"])
router.include_router(bundles.router, prefix="/api/v1")
router.include_router(bundle_pages.router)

from amoscloud_ai.autonomous.server.api.cb.router.byte.metadata import router as byte_metadata_router
router.include_router(byte_metadata_router, prefix="/api/v1")


@router.get("/health", response_model=HealthResponse, summary="Service liveness check")
async def health() -> HealthResponse:
    """Return quickly when the web process is alive."""
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


# These aliases deliberately live on the first-party health router. They keep
# critical agent and operator endpoints directly visible in FastAPI's top-level
# route table even when a dependency version preserves nested APIRouters.
@router.get("/api/v1/amomodel/status", include_in_schema=False)
async def direct_amomodel_status(request: Request):
    return await amomodel_status(request)


@router.get("/api/v1/server/cb/amosclaud", include_in_schema=False)
def direct_server_identity(request: Request):
    return server_identity(request)


@router.get("/control-bus", include_in_schema=False)
async def direct_control_bus_dashboard(request: Request):
    return await control_bus_dashboard.control_bus_dashboard(request)


@router.get("/api/v1/agent-chain/metadata/summary", include_in_schema=False)
def direct_metadata_summary(request: Request):
    return metadata_dashboard.metadata_summary(request)


@router.get("/v1/models", include_in_schema=False)
def direct_openai_models(authorization: str | None = Header(default=None)):
    return openai_compat.list_models(authorization)
