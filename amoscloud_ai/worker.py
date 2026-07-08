"""Celery worker for Amoscloud AI background tasks.

Start with:
    celery -A amoscloud_ai.worker worker --loglevel=info
Or via module:
    python -m amoscloud_ai.worker
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any, Dict

from celery import Celery

from amoscloud_ai.config import settings
from amoscloud_ai.logger import log

celery_app = Celery(
    "amoscloud_ai",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)


@celery_app.task(name="amoscloud_ai.run_pipeline", bind=True, max_retries=3)
def run_pipeline_task(self, pipeline_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a CI pipeline in the background."""
    log.info(f"[worker] Running pipeline {pipeline_id}")
    try:
        # Import here to avoid circular imports at module load time
        from amoscloud_ai.api.routes.pipelines import _pipelines
        from amoscloud_ai.models import PipelineStatus

        pipeline = _pipelines.get(pipeline_id)
        if pipeline:
            pipeline.status = PipelineStatus.RUNNING

        # ── Pipeline logic goes here ──────────────────────────────────────
        # Placeholder: mark as success immediately.
        # In production, integrate CIOrchestrator from src/core/.
        # ─────────────────────────────────────────────────────────────────

        if pipeline:
            pipeline.status = PipelineStatus.SUCCESS
            pipeline.finished_at = datetime.now(timezone.utc)

        log.info(f"[worker] Pipeline {pipeline_id} completed successfully")
        return {"pipeline_id": pipeline_id, "status": "success"}

    except Exception as exc:
        log.error(f"[worker] Pipeline {pipeline_id} failed: {exc}")
        try:
            from amoscloud_ai.api.routes.pipelines import _pipelines
            from amoscloud_ai.models import PipelineStatus
            pipeline = _pipelines.get(pipeline_id)
            if pipeline:
                pipeline.status = PipelineStatus.FAILED
                pipeline.finished_at = datetime.now(timezone.utc)
        except Exception:
            pass
        raise self.retry(exc=exc, countdown=5)


@celery_app.task(name="amoscloud_ai.run_deployment", bind=True, max_retries=3)
def run_deployment_task(self, deployment_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a deployment in the background."""
    log.info(f"[worker] Running deployment {deployment_id} to {config.get('environment')}")
    try:
        from amoscloud_ai.api.routes.deployments import _deployments
        from amoscloud_ai.models import DeploymentStatus

        dep = _deployments.get(deployment_id)
        if dep:
            dep.status = DeploymentStatus.IN_PROGRESS

        # ── Deployment logic goes here ────────────────────────────────────
        # Placeholder: mark as completed immediately.
        # In production, integrate SmartDeployer from src/core/.
        # ─────────────────────────────────────────────────────────────────

        if dep:
            dep.status = DeploymentStatus.COMPLETED
            dep.finished_at = datetime.now(timezone.utc)
            dep.message = "Deployment completed successfully"

        log.info(f"[worker] Deployment {deployment_id} completed")
        return {"deployment_id": deployment_id, "status": "completed"}

    except Exception as exc:
        log.error(f"[worker] Deployment {deployment_id} failed: {exc}")
        try:
            from amoscloud_ai.api.routes.deployments import _deployments
            from amoscloud_ai.models import DeploymentStatus
            dep = _deployments.get(deployment_id)
            if dep:
                dep.status = DeploymentStatus.FAILED
                dep.finished_at = datetime.now(timezone.utc)
        except Exception:
            pass
        raise self.retry(exc=exc, countdown=5)


def main() -> None:
    """Start the Celery worker when invoked as a module."""
    argv = ["worker", "--loglevel", settings.log_level.lower(), "-c", "2"]
    celery_app.worker_main(argv=argv)


if __name__ == "__main__":
    main()
