"""Autonomous multi-model integration for Amosclaud.

This module defines 25 specialized model jobs that all connect to the same
Autonomous Core Orchestrator and five-agent engine. A model job is a routing
profile, not necessarily a separate physical model process. Multiple jobs may
share one healthy model station, while production deployments can assign
separate model endpoints when capacity requires it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ModelJob:
    job_id: str
    name: str
    capability: str
    agent_stage: str
    system_instruction: str
    priority: int = 50
    requires_write_authorization: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


AUTONOMOUS_ENGINE = "autonomous-core-orchestrator"
AGENT_ENGINE = "amosclaud-five-agent-engine"


MODEL_JOBS: tuple[ModelJob, ...] = (
    ModelJob("model-job-01", "Objective Interpreter", "objective-understanding", "agent-1", "Normalize the user objective, constraints, desired result, and acceptance criteria.", 100),
    ModelJob("model-job-02", "Intent Classifier", "intent-routing", "agent-1", "Classify the task and choose the safest autonomous execution mode.", 95),
    ModelJob("model-job-03", "Context Builder", "context-assembly", "agent-1", "Build concise task context from repository, runtime, memory, and user authorization."),
    ModelJob("model-job-04", "Repository Scanner", "repository-perception", "agent-2", "Inspect repository files, branches, dependencies, and relevant change history.", 100),
    ModelJob("model-job-05", "Runtime Observer", "runtime-perception", "agent-2", "Inspect service health, logs, endpoints, queues, containers, and environment readiness.", 95),
    ModelJob("model-job-06", "Authentication Investigator", "auth-diagnostics", "agent-2", "Diagnose signup, login, passkey, cookie, session, and persistence failures without modifying user data.", 95),
    ModelJob("model-job-07", "Dependency Auditor", "dependency-analysis", "agent-2", "Find missing, incompatible, vulnerable, or incorrectly pinned dependencies."),
    ModelJob("model-job-08", "Failure Root-Cause Analyst", "root-cause-analysis", "agent-2", "Correlate evidence and identify the smallest defensible root cause.", 100),
    ModelJob("model-job-09", "Repair Planner", "repair-planning", "agent-3", "Create the smallest safe repair plan with rollback and verification steps.", 100),
    ModelJob("model-job-10", "Architecture Planner", "architecture-planning", "agent-3", "Design production architecture that preserves compatibility, observability, and safety."),
    ModelJob("model-job-11", "Security Planner", "security-planning", "agent-3", "Identify trust boundaries, secrets risks, authorization requirements, and safe controls.", 95),
    ModelJob("model-job-12", "Database Migration Planner", "database-planning", "agent-3", "Plan backward-compatible database migrations that preserve all existing records.", 90),
    ModelJob("model-job-13", "Model Routing Planner", "model-routing", "agent-3", "Select a healthy model station and job profile based on capability, latency, and load.", 100),
    ModelJob("model-job-14", "Code Repairer", "code-editing", "agent-4", "Apply minimal source-code repairs only inside the authorized workspace.", 100, True),
    ModelJob("model-job-15", "Frontend Repairer", "frontend-editing", "agent-4", "Repair responsive UI, state handling, accessibility, and truthful status presentation.", 90, True),
    ModelJob("model-job-16", "Backend Repairer", "backend-editing", "agent-4", "Repair APIs, services, persistence, validation, and error handling.", 100, True),
    ModelJob("model-job-17", "Infrastructure Repairer", "infrastructure-editing", "agent-4", "Repair Docker, deployment manifests, health checks, and service startup ordering.", 95, True),
    ModelJob("model-job-18", "Test Author", "test-writing", "agent-4", "Add focused regression tests that reproduce the failure and prove the repair.", 95, True),
    ModelJob("model-job-19", "Rollback Controller", "rollback", "agent-4", "Restore the last verified state when a repair fails verification.", 100, True),
    ModelJob("model-job-20", "Compiler Verifier", "compile-verification", "agent-5", "Compile changed modules and report exact failures."),
    ModelJob("model-job-21", "Test Verifier", "test-verification", "agent-5", "Run focused and required test suites and preserve command evidence.", 100),
    ModelJob("model-job-22", "Security Verifier", "security-verification", "agent-5", "Verify authorization, data preservation, secret handling, and unsafe regressions.", 95),
    ModelJob("model-job-23", "Deployment Verifier", "deployment-verification", "agent-5", "Verify health probes, service readiness, model inference, and rollback capability."),
    ModelJob("model-job-24", "Evidence Reporter", "evidence-reporting", "agent-5", "Summarize changed files, elapsed time, passed checks, failed checks, and unresolved blockers.", 100),
    ModelJob("model-job-25", "Memory Curator", "memory-learning", "agent-5", "Store reusable repository lessons only after verified completion; never store secrets.", 85),
)

_BY_ID = {job.job_id: job for job in MODEL_JOBS}
_BY_CAPABILITY = {job.capability: job for job in MODEL_JOBS}


def list_model_jobs() -> list[dict[str, object]]:
    """Return all 25 jobs for APIs and dashboards."""
    return [job.to_dict() for job in MODEL_JOBS]


def get_model_job(job_id: str) -> ModelJob:
    try:
        return _BY_ID[job_id]
    except KeyError as exc:
        raise KeyError(f"Unknown autonomous model job: {job_id}") from exc


def route_model_job(capability: str, *, write_authorized: bool = False) -> ModelJob:
    """Route work to a specialized job while enforcing write authorization."""
    try:
        job = _BY_CAPABILITY[capability]
    except KeyError as exc:
        raise KeyError(f"No autonomous model job provides capability: {capability}") from exc
    if job.requires_write_authorization and not write_authorized:
        raise PermissionError(f"{job.job_id} requires explicit write authorization")
    return job


def jobs_for_agent(agent_stage: str) -> tuple[ModelJob, ...]:
    return tuple(job for job in MODEL_JOBS if job.agent_stage == agent_stage)


def integration_manifest(enabled_job_ids: Iterable[str] | None = None) -> dict[str, object]:
    selected = MODEL_JOBS if enabled_job_ids is None else tuple(get_model_job(job_id) for job_id in enabled_job_ids)
    return {
        "name": "Autonomous_models_integra",
        "autonomous_engine": AUTONOMOUS_ENGINE,
        "agent_engine": AGENT_ENGINE,
        "model_job_count": len(selected),
        "model_jobs": [job.to_dict() for job in selected],
        "policy": {
            "shared_orchestrator": True,
            "health_required": True,
            "verified_output_only": True,
            "write_authorization_required": True,
            "fallback_allowed": True,
        },
    }
