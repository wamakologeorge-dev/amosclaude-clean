"""Celery worker for Amosclaud AI background tasks."""

from __future__ import annotations

import asyncio
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
    """Execute and persist one pipeline, including autonomous task evidence."""
    log.info("[worker] Running pipeline %s", pipeline_id)
    try:
        from amoscloud_ai.api.routes.pipelines import _get, _save
        from amoscloud_ai.copilot import pipeline_reply
        from amoscloud_ai.models import PipelineStatus

        pipeline = _get(pipeline_id)
        if pipeline:
            pipeline.status = PipelineStatus.RUNNING
            running_reply = (
                "Amosclaud Autonomous Agent: inspecting, planning, acting, and verifying."
                if payload.get("trigger") == "autonomous"
                else pipeline_reply(PipelineStatus.RUNNING)
            )
            pipeline.message = running_reply
            pipeline.copilot_reply = running_reply
            if pipeline.jobs:
                pipeline.jobs[0].status = PipelineStatus.RUNNING
                pipeline.jobs[0].started_at = datetime.now(timezone.utc)
                pipeline.jobs[0].logs.append(running_reply)
            _save(pipeline, payload)

        if payload.get("trigger") == "autonomous":
            from amoscloud_ai.autonomous_server import run_autonomous_server

            run_payload = payload.get("payload", {})
            autonomous = run_autonomous_server(
                run_payload.get("mode", "autonomous-check"),
                run_payload.get("objective", "amosclaud.com autonomous operations"),
                run_payload.get("metadata", {}),
            )
            success = autonomous.status == PipelineStatus.SUCCESS
            reports_count = len(autonomous.checks)
            jobs_count = 1

            # Reload before writing so a separate Celery process always updates the
            # durable pipeline row rather than an in-memory object from another process.
            pipeline = _get(pipeline_id)
            if pipeline:
                pipeline.status = autonomous.status
                pipeline.finished_at = datetime.now(timezone.utc)
                pipeline.message = autonomous.reply
                pipeline.copilot_reply = autonomous.reply
                if pipeline.jobs:
                    pipeline.jobs[0].status = autonomous.status
                    pipeline.jobs[0].finished_at = pipeline.finished_at
                    pipeline.jobs[0].logs.extend(autonomous.logs)
                    pipeline.jobs[0].logs.append(autonomous.reply)
                _save(pipeline, payload)
        else:
            from src.core.ci_orchestrator import CIOrchestrator

            orchestrator = CIOrchestrator(config=payload)
            success = asyncio.run(orchestrator.start_pipeline(payload.get("trigger", "manual"), payload))
            reports_count = len(orchestrator.reports)
            jobs_count = len(orchestrator.jobs)
            pipeline = _get(pipeline_id)
            if pipeline:
                pipeline.status = PipelineStatus.SUCCESS if success else PipelineStatus.FAILED
                pipeline.finished_at = datetime.now(timezone.utc)
                if orchestrator.jobs:
                    pipeline.jobs = orchestrator.jobs
                reply = pipeline_reply(pipeline.status)
                pipeline.message = reply
                pipeline.copilot_reply = reply
                if pipeline.jobs:
                    pipeline.jobs[0].status = pipeline.status
                    pipeline.jobs[0].finished_at = pipeline.finished_at
                    pipeline.jobs[0].logs.append(reply)
                _save(pipeline, payload)

        status = "success" if success else "failed"
        log.info("[worker] Pipeline %s finished with status: %s", pipeline_id, status)
        return {
            "pipeline_id": pipeline_id,
            "status": status,
            "jobs_count": jobs_count,
            "reports_count": reports_count,
        }
    except Exception as exc:
        log.exception("[worker] Pipeline %s failed", pipeline_id)
        try:
            from amoscloud_ai.api.routes.pipelines import _get, _save
            from amoscloud_ai.models import PipelineStatus

            pipeline = _get(pipeline_id)
            if pipeline:
                pipeline.status = PipelineStatus.FAILED
                pipeline.finished_at = datetime.now(timezone.utc)
                reply = "Amosclaud Autonomous Agent: background execution stopped safely."
                pipeline.message = reply
                pipeline.copilot_reply = reply
                for job in pipeline.jobs:
                    if job.status not in (PipelineStatus.SUCCESS, PipelineStatus.CANCELLED):
                        job.status = PipelineStatus.FAILED
                        job.finished_at = pipeline.finished_at
                        job.logs.append(f"Worker failure category: {type(exc).__name__}")
                _save(pipeline, payload, type(exc).__name__)
        except Exception:
            log.exception("Unable to persist failed pipeline %s", pipeline_id)
        raise self.retry(exc=exc, countdown=5)


@celery_app.task(name="amoscloud_ai.run_deployment", bind=True, max_retries=3)
def run_deployment_task(self, deployment_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one deployment task."""
    log.info("[worker] Running deployment %s", deployment_id)
    try:
        from amoscloud_ai.api.routes.deployments import _deployments
        from amoscloud_ai.copilot import deployment_reply
        from amoscloud_ai.models import DeploymentStatus
        from src.core.smart_deployer import SmartDeployer

        dep = _deployments.get(deployment_id)
        if dep:
            dep.status = DeploymentStatus.IN_PROGRESS
            dep.message = deployment_reply(dep.status)
            dep.copilot_reply = dep.message

        deployer = SmartDeployer(config=config)
        success = asyncio.run(
            deployer.deploy(config.get("version") or "latest", config.get("environment") or "development")
        )
        if dep:
            if success:
                dep.status = DeploymentStatus.COMPLETED
            else:
                dep.status = (
                    DeploymentStatus.ROLLED_BACK
                    if deployer.status.value == "rolled_back"
                    else DeploymentStatus.FAILED
                )
            dep.finished_at = datetime.now(timezone.utc)
            dep.message = deployment_reply(dep.status)
            dep.copilot_reply = dep.message
        return {"deployment_id": deployment_id, "status": dep.status.value if dep else ("completed" if success else "failed")}
    except Exception as exc:
        log.exception("Deployment %s failed", deployment_id)
        raise self.retry(exc=exc, countdown=5)


@celery_app.task(name="amoscloud_ai.run_global_task", bind=True, max_retries=2)
def run_global_task(self, task_id: str) -> dict[str, str]:
    try:
        from amoscloud_ai.cloud_task_runner import execute_cloud_task

        execute_cloud_task(task_id)
        return {"task_id": task_id, "dispatched": "true"}
    except Exception as exc:
        log.exception("Global task %s failed in worker", task_id)
        raise self.retry(exc=exc, countdown=10)


def main() -> None:
    celery_app.worker_main(argv=["worker", "--loglevel", settings.log_level.lower(), "-c", "2"])


if __name__ == "__main__":
    main()
