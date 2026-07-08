"""Health-check route."""

from datetime import datetime, timezone

from fastapi import APIRouter

from amoscloud_ai.config import settings
from amoscloud_ai.models import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Service health check")
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        environment=settings.environment,
        timestamp=datetime.now(timezone.utc),
    )
