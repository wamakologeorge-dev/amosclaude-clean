"""Celery workers for Amosclaud background tasks.

The API and worker may run in different processes, so task state must always be
read from and written to the persistent pipeline database. Never rely on a
process-local dictionary for a user-visible task.
"""

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
    """Receive, execute, verify, and persist one pipeline task."""
    from amoscloud_ai.api.routes.pipelines import _get, _save
    from amoscloud_ai.models import PipelineStatus

    log.info("[worker] Received pipeline task %s", pipeline_id)
    pipeline = _get(pipeline_id)
    if pipeline is None:
        raise ValueError(f"Pipeline {pipeline_id!r} was not persisted before dispatch")

    pipeline.status = PipelineStatus.RUNNING
    pipeline.message = "Amosclaud Autonomous Agent: task received. Execution started."
    pipeline.copilot_reply = pipeline.message
    if pipeline.jobs:
        job = pipeline.jobs[0]
        job.status = PipelineStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        job.logs.append("Task received by the execution worker.")
        job.logs.append("Execution started: understand → inspect → plan → act → verify → report.")
    _save(pipeline, payload)

    try:
        if payload.get("trigger") == "autonomous":
            from amoscloud_ai.autonomous_server import run_autonomous_server

            run_payload = payload.get("payload", {})
            result = run_autonomous_server(
                run_payload.get("mode", "autonomous-check"),
                run_payload.get("objective", "amosclaud.com autonomous operations"),
                run_payload.get("metadata", {}),
            )
            pipeline.status = result.status
            pipeline.message = result.reply
            pipeline.copilot_reply = result.reply
            reports_count = len(result.checks)
            jobs_count = 1
            if pipeline.jobs:
                pipeline.jobs[0].logs.extend(result.logs)
        else:
            from src.core.ci_orchestrator import CIOrchestrator

            orchestrator = CIOrchestrator(config=payload)
            successful = asyncio.run(
                orchestrator.start_pipeline(payload.get("trigger", "manual"), payload)
            )
            pipeline.status = PipelineStatus.SUCCESS if successful else PipelineStatus.FAILED
            pipeline.message = (
                "Amosclaud Autonomous Agent: pipeline completed with verified evidence."
                if successful
                else "Amosclaud Autonomous Agent: pipeline stopped after a blocking verification failure."
            )
            pipeline.copilot_reply = pipeline.message
            if orchestrator.jobs:
                pipeline.jobs = orchestrator.jobs
            reports_count = len(orchestrator.reports)
            jobs_count = len(orchestrator.jobs)

        pipeline.finished_at = datetime.now(timezone.utc)
        if pipeline.jobs:
            pipeline.jobs[0].status = pipeline.status
            pipeline.jobs[0].finished_at = pipeline.finished_at
            pipeline.jobs[0].logs.append(pipeline.message or "Task finished.")
        _save(pipeline, payload)

        result_status = pipeline.status.value
        log.info("[worker] Pipeline %s finished with status: %s", pipeline_id, result_status)
        return {
            "pipeline_id": pipeline_id,
            "status": result_status,
            "jobs_count": jobs_count,
            "reports_count": reports_count,
        }
    except Exception as exc:
        log.exception("[worker] Pipeline %s failed", pipeline_id)
        pipeline = _get(pipeline_id) or pipeline
        pipeline.status = PipelineStatus.FAILED
        pipeline.finished_at = datetime.now(timezone.utc)
        pipeline.message = f"Amosclaud Autonomous Agent: execution failed safely: {type(exc).__name__}."
        pipeline.copilot_reply = pipeline.message
        for job in pipeline.jobs:
            if job.status not in (PipelineStatus.SUCCESS, PipelineStatus.CANCELLED):
                job.status = PipelineStatus.FAILED
                job.finished_at = pipeline.finished_at
                job.logs.append(f"Runtime error: {type(exc).__name__}: {exc}")
        _save(pipeline, payload, str(exc))
        raise self.retry(exc=exc, countdown=5)


@celery_app.task(name="amoscloud_ai.run_deployment", bind=True, max_retries=3)
def run_deployment_task(self, deployment_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a deployment in the background."""
    log.info("[worker] Running deployment %s to %s", deployment_id, config.get("environment"))
    try:
        from amoscloud_ai.api.routes.deployments import _deployments
        from amoscloud_ai.copilot import deployment_reply
        from amoscloud_ai.models import DeploymentStatus

        dep = _deployments.get(deployment_id)
        if dep:
            dep.status = DeploymentStatus.IN_PROGRESS
            dep.message = deployment_reply(DeploymentStatus.IN_PROGRESS)
            dep.copilot_reply = dep.message

        from src.core.smart_deployer import SmartDeployer

        deployer = SmartDeployer(config=config)
        success = asyncio.run(
            deployer.deploy(
                config.get("version") or "latest",
                config.get("environment") or "development",
            )
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

        result_status = dep.status.value if dep else ("completed" if success else "failed")
        return {"deployment_id": deployment_id, "status": result_status}
    except Exception as exc:
        log.exception("[worker] Deployment %s failed", deployment_id)
        try:
            from amoscloud_ai.api.routes.deployments import _deployments
            from amoscloud_ai.copilot import deployment_reply
            from amoscloud_ai.models import DeploymentStatus

            dep = _deployments.get(deployment_id)
            if dep:
                dep.status = DeploymentStatus.FAILED
                dep.finished_at = datetime.now(timezone.utc)
                dep.message = deployment_reply(DeploymentStatus.FAILED)
                dep.copilot_reply = dep.message
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
    celery_app.worker_main(argv=["worker", "--loglevel", settings.log_level.lower(), "-c", "2"])


if __name__ == "__main__":
    main()
