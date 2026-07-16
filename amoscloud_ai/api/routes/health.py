"""Fast liveness and detailed autonomous-readiness routes."""

from __future__ import annotations

import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter

from amoscloud_ai import provider
from amoscloud_ai.api.routes import model_server_folder
from amoscloud_ai.config import settings
from amoscloud_ai.models import HealthResponse

router = APIRouter(tags=["health"])
router.include_router(model_server_folder.router, prefix="/api/v1")


@router.get("/health", response_model=HealthResponse, summary="Service liveness check")
async def health() -> HealthResponse:
    """Return quickly when the web process is alive.

    Railway should use this endpoint. Model, broker, and agent availability are
    intentionally excluded so an optional dependency cannot make the web service
    fail its platform health check.
    """
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        environment=settings.environment,
        timestamp=datetime.now(timezone.utc),
    )


def _broker_status() -> dict[str, object]:
    parsed = urlparse(settings.celery_broker_url)
    host = parsed.hostname
    port = parsed.port or {"redis": 6379, "rediss": 6379, "amqp": 5672, "amqps": 5671}.get(parsed.scheme)
    if not host or not port:
        return {"configured": False, "reachable": False, "execution": "inline-fallback"}
    try:
        with socket.create_connection((host, port), timeout=0.35):
            return {"configured": True, "reachable": True, "scheme": parsed.scheme, "execution": "background-worker"}
    except OSError:
        return {"configured": True, "reachable": False, "scheme": parsed.scheme, "execution": "inline-fallback"}


@router.get("/ready", summary="Autonomous service readiness")
async def readiness() -> dict[str, object]:
    """Return safe component readiness.

    ``ready`` means a model-network station has recently reported ready.
    ``configured_unverified`` means a provider is configured but has not been
    proven by this lightweight endpoint. ``degraded`` means no provider path is
    configured. Use a real task or the protected provider probe for end-to-end
    inference verification.
    """
    provider_state = provider.status()
    broker_state = _broker_status()
    model_verified = bool(provider_state.get("model_network", {}).get("ready"))
    model_configured = bool(
        provider_state.get("self_hosted_configured")
        or provider_state.get("amosclaud_api_configured")
        or (
            provider_state.get("external_adapters_enabled")
            and provider_state.get("openai_configured")
        )
    )
    if model_verified:
        readiness_state = "ready"
    elif model_configured:
        readiness_state = "configured_unverified"
    else:
        readiness_state = "degraded"

    return {
        "status": readiness_state,
        "web": {"ready": True},
        "autonomous_api": {
            "ready": True,
            "route": "/api/v1/agent/run",
            "result_route": "/api/v1/pipelines/{pipeline_id}",
            "auth": ["session", "X-Amosclaud-Owner-Key", "X-API-Key"],
        },
        "worker": broker_state,
        "model_runtime": {
            "configured": model_configured,
            "verified_ready": model_verified,
        },
        "provider": provider_state,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
