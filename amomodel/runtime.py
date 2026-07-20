"""Governed AmoModel lifecycle and Autonomous job scheduling runtime."""

from __future__ import annotations

import uuid
from pathlib import Path
from threading import RLock
from typing import Any

from sqlalchemy import select

from Amosclaud.platform_bus import platform_bus_from_environment
from database.models import AutonomousJob, CIPipeline, CIStatus, Repository
from database.session import create_database, session_scope

from .service_graph import ServiceGraph
from .state import RuntimeState, StateStore


class AmoModelRuntime:
    """Truthful control plane for Amosclaud services and Autonomous work.

    AmoModel does not execute arbitrary shell commands or claim that work has
    completed. It owns lifecycle/readiness, creates authoritative database jobs,
    attaches CI evidence, and exposes status for workers and the platform UI.
    """

    def __init__(self, state_path: Path | None = None) -> None:
        self.store = StateStore(state_path)
        self.graph = ServiceGraph()
        self._lock = RLock()
        create_database()

    def status(self) -> dict[str, Any]:
        state = self.store.load()
        return self._snapshot(state)

    def power_on(self, actor: str) -> dict[str, Any]:
        with self._lock:
            state = self.store.load()
            if state.state in {"ready", "busy"}:
                return self._snapshot(state)
            state.state = "starting"
            state.last_error = None
            self.store.record(state, "power_on_started", actor)
            state.services = self.graph.startup()
            state.state = "ready" if self.graph.healthy(state.services) else "degraded"
            self.store.record(state, "power_on_finished", actor, state.state)
            return self._snapshot(state)

    def power_off(self, actor: str) -> dict[str, Any]:
        with self._lock:
            state = self.store.load()
            state.state = "stopping"
            self.store.record(state, "power_off_started", actor)
            state.services = self.graph.shutdown()
            state.state = "off"
            state.last_error = None
            self.store.record(state, "power_off_finished", actor)
            return self._snapshot(state)

    def restart(self, actor: str) -> dict[str, Any]:
        with self._lock:
            self.power_off(actor)
            result = self.power_on(actor)
            state = self.store.load()
            self.store.record(state, "restart_finished", actor)
            return result

    def execute(
        self,
        actor: str,
        objective: str,
        wake: bool = True,
        *,
        repository_id: int | None = None,
        pull_request_id: int | None = None,
        requested_by_id: int | None = None,
        mode: str = "plan",
        target_file: str | None = None,
        error_context: str | None = None,
        commit_sha: str = "uncommitted",
    ) -> dict[str, Any]:
        """Accept an objective or queue governed Autonomous work.

        With no repository ID this remains a truthful planning/readiness request.
        With a repository ID it creates a persisted CI pipeline and AutonomousJob.
        The job remains queued until an approved worker claims it; AmoModel never
        reports a repair as complete without CI verification evidence.
        """
        clean = objective.strip()
        if not clean:
            raise ValueError("objective must not be empty")
        normalized_mode = mode.strip().lower()
        if normalized_mode not in {"plan", "build", "test", "review", "deploy", "monitor", "fix"}:
            raise ValueError("unsupported AmoModel execution mode")

        with self._lock:
            state = self.store.load()
            if state.state == "off" and wake:
                self.power_on(actor)
                state = self.store.load()
            if state.state != "ready":
                raise RuntimeError(f"AmoModel is not ready; current state is {state.state}")

            state.state = "busy"
            self.store.record(state, "execution_started", actor, f"{normalized_mode}: {clean}")
            try:
                result: dict[str, Any] = {
                    "objective": clean,
                    "accepted": True,
                    "mode": normalized_mode,
                    "engine": "amosclaud-governed-control-plane",
                    "service_evidence": self.graph.evidence(state.services),
                }
                if repository_id is None:
                    result.update(
                        {
                            "status": "planned",
                            "message": "Objective accepted for governed planning; no repository job was created.",
                            "next_action": "Provide repository_id to queue an Autonomous platform job.",
                        }
                    )
                else:
                    result.update(
                        self._queue_job(
                            repository_id=repository_id,
                            pull_request_id=pull_request_id,
                            requested_by_id=requested_by_id,
                            objective=clean,
                            mode=normalized_mode,
                            target_file=target_file,
                            error_context=error_context,
                            commit_sha=commit_sha,
                        )
                    )
                state.executions += 1
                state.state = "ready"
                state.last_error = None
                self.store.record(state, "execution_finished", actor, result.get("task_id", clean))
                result["runtime"] = self._snapshot(state)
                return result
            except Exception as exc:
                state.state = "degraded"
                state.last_error = str(exc)
                self.store.record(state, "execution_failed", actor, str(exc))
                raise

    def job_status(self, task_id: str) -> dict[str, Any]:
        clean = task_id.strip()
        if not clean:
            raise ValueError("task_id is required")
        bus = platform_bus_from_environment()
        if bus is not None:
            return bus.execute(bus.frame("platform.job.status", {"task_id": clean})).json()
        with session_scope() as session:
            job = session.scalar(select(AutonomousJob).where(AutonomousJob.task_id == clean))
            if job is None:
                raise LookupError("autonomous job not found")
            return {
                "task_id": job.task_id,
                "repository_id": job.repository_id,
                "pull_request_id": job.pull_request_id,
                "ci_pipeline_id": job.ci_pipeline_id,
                "agent_type": job.agent_type,
                "status": job.status.value,
                "objective": job.objective,
                "result_summary": job.result_summary,
                "ci_status": job.ci_pipeline.status.value if job.ci_pipeline else None,
                "verification_id": job.ci_pipeline.verification_id if job.ci_pipeline else None,
            }

    def _queue_job(
        self,
        *,
        repository_id: int,
        pull_request_id: int | None,
        requested_by_id: int | None,
        objective: str,
        mode: str,
        target_file: str | None,
        error_context: str | None,
        commit_sha: str,
    ) -> dict[str, Any]:
        task_id = f"amomodel-{uuid.uuid4().hex}"
        with session_scope() as session:
            repository = session.get(Repository, repository_id)
            if repository is None:
                raise LookupError("repository not found")
            pipeline = CIPipeline(
                repository_id=repository_id,
                pull_request_id=pull_request_id,
                commit_sha=(commit_sha.strip() or "uncommitted")[:64],
                status=CIStatus.PENDING,
                execution_logs=f"Queued by AmoModel in {mode} mode.",
            )
            session.add(pipeline)
            session.flush()
            job = AutonomousJob(
                task_id=task_id,
                agent_type="amosclaud-fixer" if mode == "fix" else "amosclaud-autonomous",
                requested_by_id=requested_by_id,
                repository_id=repository_id,
                pull_request_id=pull_request_id,
                ci_pipeline_id=pipeline.id,
                objective=objective,
                target_file=(target_file or "")[:500] or None,
                error_context=(error_context or "")[:20_000] or None,
            )
            session.add(job)
            session.flush()
            response = {
                "status": "queued",
                "message": "Autonomous job and CI pipeline created in the shared platform database.",
                "task_id": task_id,
                "repository_id": repository_id,
                "repository": repository.name,
                "pull_request_id": pull_request_id,
                "ci_pipeline_id": pipeline.id,
                "agent_type": job.agent_type,
                "verification_required": True,
            }
        return response

    def _snapshot(self, state: RuntimeState) -> dict[str, Any]:
        services = state.services
        return {
            "name": "AmoModel",
            "version": state.version,
            "role": "governed-control-plane",
            "state": state.state,
            "updated_at": state.updated_at,
            "services": services,
            "service_evidence": self.graph.evidence(services),
            "healthy": state.state == "ready" and self.graph.healthy(services),
            "last_error": state.last_error,
            "executions": state.executions,
            "capabilities": [
                "runtime-lifecycle",
                "service-readiness",
                "autonomous-job-scheduling",
                "ci-pipeline-creation",
                "job-status",
                "audit-evidence",
            ],
            "audit": state.audit[-20:],
        }


_RUNTIME: AmoModelRuntime | None = None


def get_runtime() -> AmoModelRuntime:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = AmoModelRuntime()
    return _RUNTIME
