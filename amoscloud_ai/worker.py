"""Celery worker for Amosclaud AI background tasks.

Start with:
    celery -A amoscloud_ai.worker worker --loglevel=info
Or via module:
    python -m amoscloud_ai.worker
"""

from __future__ import annotations

import asyncio
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
        from amoscloud_ai.copilot import pipeline_reply
        from amoscloud_ai.models import PipelineStatus

        pipeline = _pipelines.get(pipeline_id)
        if pipeline:
            pipeline.status = PipelineStatus.RUNNING
            reply = pipeline_reply(PipelineStatus.RUNNING)
            pipeline.message = reply
            pipeline.copilot_reply = reply
            if pipeline.jobs:
                pipeline.jobs[0].status = PipelineStatus.RUNNING
                pipeline.jobs[0].started_at = datetime.now(timezone.utc)
                pipeline.jobs[0].logs.append(reply)

        # ── Pipeline logic ────────────────────────────────────────────────
        if payload.get("trigger") == "autonomous":
            from amoscloud_ai.autonomous_server import run_autonomous_server

            run_payload = payload.get("payload", {})
            result = run_autonomous_server(
                run_payload.get("mode", "autonomous-check"),
                run_payload.get("objective", "amosclaud.com autonomous operations"),
                run_payload.get("metadata", {}),
            )
            success = result.status == PipelineStatus.SUCCESS
            orchestrator_jobs = []
            reports_count = len(result.checks)
            if pipeline and pipeline.jobs:
                pipeline.jobs[0].logs.extend(result.logs)
        else:
            from src.core.ci_orchestrator import CIOrchestrator

            orchestrator = CIOrchestrator(config=payload)
            success = asyncio.run(
                orchestrator.start_pipeline(payload.get("trigger", "manual"), payload)
            )
            orchestrator_jobs = orchestrator.jobs
            reports_count = len(orchestrator.reports)
        # ─────────────────────────────────────────────────────────────────

        if pipeline:
            pipeline.status = PipelineStatus.SUCCESS if success else PipelineStatus.FAILED
            pipeline.finished_at = datetime.now(timezone.utc)
            # Attach any job/report data captured by the orchestrator
            if orchestrator_jobs:
                pipeline.jobs = orchestrator_jobs
            reply = pipeline_reply(pipeline.status)
            pipeline.message = reply
            pipeline.copilot_reply = reply
            if pipeline.jobs:
                pipeline.jobs[0].status = pipeline.status
                pipeline.jobs[0].finished_at = pipeline.finished_at
                pipeline.jobs[0].logs.append(reply)

        result_status = "success" if success else "failed"
        log.info(f"[worker] Pipeline {pipeline_id} finished with status: {result_status}")
        return {
            "pipeline_id": pipeline_id,
            "status": result_status,
            "jobs_count": len(orchestrator_jobs),
            "reports_count": reports_count,
        }

    except Exception as exc:
        log.error(f"[worker] Pipeline {pipeline_id} failed: {exc}")
        try:
            from amoscloud_ai.api.routes.pipelines import _pipelines
            from amoscloud_ai.copilot import pipeline_reply
            from amoscloud_ai.models import PipelineStatus
            pipeline = _pipelines.get(pipeline_id)
            if pipeline:
                pipeline.status = PipelineStatus.FAILED
                pipeline.finished_at = datetime.now(timezone.utc)
                reply = pipeline_reply(PipelineStatus.FAILED)
                pipeline.message = reply
                pipeline.copilot_reply = reply
                for job in pipeline.jobs:
                    if job.status not in (PipelineStatus.SUCCESS, PipelineStatus.CANCELLED):
                        job.status = PipelineStatus.FAILED
                        job.finished_at = pipeline.finished_at
                        job.logs.append(reply)
        except Exception:
            pass
        raise self.retry(exc=exc, countdown=5)


@celery_app.task(name="amoscloud_ai.run_deployment", bind=True, max_retries=3)
def run_deployment_task(self, deployment_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a deployment in the background."""
    log.info(f"[worker] Running deployment {deployment_id} to {config.get('environment')}")
    try:
        from amoscloud_ai.api.routes.deployments import _deployments
        from amoscloud_ai.copilot import deployment_reply
        from amoscloud_ai.models import DeploymentStatus

        dep = _deployments.get(deployment_id)
        if dep:
            dep.status = DeploymentStatus.IN_PROGRESS
            reply = deployment_reply(DeploymentStatus.IN_PROGRESS)
            dep.message = reply
            dep.copilot_reply = reply

        # ── Deployment logic ──────────────────────────────────────────────
        from src.core.smart_deployer import SmartDeployer

        deployer = SmartDeployer(config=config)
        success = asyncio.run(
            deployer.deploy(
                config.get("version") or "latest",
                config.get("environment") or "development",
            )
        )
        # ─────────────────────────────────────────────────────────────────

        if dep:
            # Map SmartDeployer's final status back to the API model
            if success:
                dep.status = DeploymentStatus.COMPLETED
            else:
                # deployer.status reflects FAILED or ROLLED_BACK
                deployer_status = deployer.status.value  # e.g. "rolled_back" or "failed"
                dep.status = (
                    DeploymentStatus.ROLLED_BACK
                    if deployer_status == "rolled_back"
                    else DeploymentStatus.FAILED
                )
            dep.finished_at = datetime.now(timezone.utc)
            reply = deployment_reply(dep.status)
            dep.message = reply
            dep.copilot_reply = reply

        result_status = dep.status.value if dep else ("completed" if success else "failed")
        log.info(f"[worker] Deployment {deployment_id} finished with status: {result_status}")
        return {"deployment_id": deployment_id, "status": result_status}

    except Exception as exc:
        log.error(f"[worker] Deployment {deployment_id} failed: {exc}")
        try:
            from amoscloud_ai.api.routes.deployments import _deployments
            from amoscloud_ai.copilot import deployment_reply
            from amoscloud_ai.models import DeploymentStatus
            dep = _deployments.get(deployment_id)
            if dep:
                dep.status = DeploymentStatus.FAILED
                dep.finished_at = datetime.now(timezone.utc)
                reply = deployment_reply(DeploymentStatus.FAILED)
                dep.message = reply
                dep.copilot_reply = reply
        except Exception:
            pass
        raise self.retry(exc=exc, countdown=5)



@celery_app.task(name="amoscloud_ai.run_global_task", bind=True, max_retries=2)
def run_global_task(self, task_id: str) -> dict[str, str]:
    """Execute one approved Global Task Router job."""
    try:
        from amoscloud_ai.cloud_task_runner import execute_cloud_task

        execute_cloud_task(task_id)
        return {"task_id": task_id, "dispatched": "true"}
    except Exception as exc:
        log.exception("Global task %s failed in worker", task_id)
        raise self.retry(exc=exc, countdown=10)


def main() -> None:
    """Start the Celery worker when invoked as a module."""
    argv = ["worker", "--loglevel", settings.log_level.lower(), "-c", "2"]
    celery_app.worker_main(argv=argv)


if __name__ == "__main__":
    main()
