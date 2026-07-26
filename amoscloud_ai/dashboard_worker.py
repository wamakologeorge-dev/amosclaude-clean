"""Celery entry point for the owner-scoped workflow dashboard.

The dashboard API only creates queued records. All untrusted commands are loaded
and executed by this worker through the isolated runner.
"""

from __future__ import annotations

from typing import Any

from amoscloud_ai.worker import celery_app


@celery_app.task(
    name="amoscloud_ai.run_dashboard_project",
    bind=True,
    max_retries=1,
    acks_late=True,
)
def run_dashboard_project(
    self: Any,
    run_id: str,
    owner_user_id: int,
) -> dict[str, str]:
    try:
        from app import execute_queued_run

        status = execute_queued_run(run_id, owner_user_id)
        return {"run_id": run_id, "status": status}
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=10)
        raise
