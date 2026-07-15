"""Health-check route and model-server folder bootstrap routes."""

from datetime import datetime, timezone

from fastapi import APIRouter

from amoscloud_ai.config import settings
from amoscloud_ai.models import HealthResponse
from amoscloud_ai.api.routes import model_server_folder

router = APIRouter(tags=["health"])
router.include_router(model_server_folder.router, prefix="/api/v1")


@router.get("/health", response_model=HealthResponse, summary="Service health check")
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        environment=settings.environment,
        timestamp=datetime.now(timezone.utc),
    )
