"""Deployment management routes."""

import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, HTTPException

from amoscloud_ai.logger import log
from amoscloud_ai.models import DeploymentConfig, DeploymentResponse, DeploymentStatus

router = APIRouter(prefix="/deployments", tags=["deployments"])

# In-memory store (replace with DB in production)
_deployments: dict[str, DeploymentResponse] = {}


@router.get("", response_model=List[DeploymentResponse], summary="List all deployments")
async def list_deployments() -> List[DeploymentResponse]:
    return list(_deployments.values())


@router.get("/{deployment_id}", response_model=DeploymentResponse, summary="Get a deployment")
async def get_deployment(deployment_id: str) -> DeploymentResponse:
    dep = _deployments.get(deployment_id)
    if not dep:
        raise HTTPException(status_code=404, detail=f"Deployment {deployment_id!r} not found")
    return dep


@router.post("", response_model=DeploymentResponse, status_code=201, summary="Start a deployment")
async def start_deployment(config: DeploymentConfig) -> DeploymentResponse:
    deployment_id = str(uuid.uuid4())
    log.info(f"Starting deployment {deployment_id} to {config.environment}")

    dep = DeploymentResponse(
        id=deployment_id,
        status=DeploymentStatus.PENDING,
        environment=config.environment.value,
        version=config.version,
        started_at=datetime.now(timezone.utc),
    )
    _deployments[deployment_id] = dep

    # Kick off background task
    try:
        from amoscloud_ai.worker import run_deployment_task
        run_deployment_task.delay(deployment_id, config.model_dump())
    except Exception:
        log.warning("Celery unavailable – running deployment stub")
        dep.status = DeploymentStatus.COMPLETED
        dep.finished_at = datetime.now(timezone.utc)
        dep.message = "Deployment completed (stub mode)"

    return dep


@router.post("/{deployment_id}/rollback", response_model=DeploymentResponse, summary="Rollback a deployment")
async def rollback_deployment(deployment_id: str) -> DeploymentResponse:
    dep = _deployments.get(deployment_id)
    if not dep:
        raise HTTPException(status_code=404, detail=f"Deployment {deployment_id!r} not found")

    log.warning(f"Rolling back deployment {deployment_id}")
    dep.status = DeploymentStatus.ROLLED_BACK
    dep.finished_at = datetime.now(timezone.utc)
    dep.message = "Rolled back successfully"
    return dep
