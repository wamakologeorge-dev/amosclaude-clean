"""Unified API chain for browser, Codex, and future Amosclaud connectors.

The chain preserves identity and conversation context, selects deterministic or
model-assisted execution, returns terminal evidence, and records whether a failed
deployment needs rollback.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from amoscloud_ai.autonomous_server import run_autonomous_server
from amoscloud_ai.models import PipelineStatus

ALLOWED_MODES = {"autonomous-check", "build", "fix", "deploy", "monitor"}


@dataclass
class AutonomousChainRequest:
    user_id: int
    user_name: str
    objective: str
    mode: str = "autonomous-check"
    branch: str = "main"
    conversation_id: str | None = None
    source: str = "api"
    use_model: bool = False
    apply_changes: bool = False
    metadata: dict[str, Any] | None = None


@dataclass
class AutonomousChainResult:
    payload: dict[str, Any]


def execute_autonomous_chain(request: AutonomousChainRequest) -> AutonomousChainResult:
    mode = request.mode.strip().lower()
    if mode not in ALLOWED_MODES:
        raise ValueError(f"Mode must be one of: {', '.join(sorted(ALLOWED_MODES))}")

    objective = request.objective.strip()
    if not objective:
        raise ValueError("Objective is required")

    run_id = str(uuid.uuid4())
    conversation_id = request.conversation_id or str(uuid.uuid4())
    metadata = dict(request.metadata or {})
    metadata.update(
        {
            "api_chain": "amosclaud-autonomous-v1",
            "run_id": run_id,
            "conversation_id": conversation_id,
            "source": request.source,
            "user_id": request.user_id,
            "user_name": request.user_name,
            "branch": request.branch,
            "use_agent": bool(request.use_model),
            "apply_changes": bool(request.apply_changes or mode == "fix"),
        }
    )

    result = run_autonomous_server(mode, objective, metadata)
    checks = [
        {"name": item.name, "status": item.status, "summary": item.summary, "details": item.details}
        for item in result.checks
    ]
    model_used = any(item.name == "agentic-cloud-core" or item.name.startswith("agent-") for item in result.checks)
    rollback_recommended = mode == "deploy" and result.status == PipelineStatus.FAILED

    return AutonomousChainResult(
        {
            "accepted": True,
            "chain": "amosclaud-autonomous-v1",
            "run_id": run_id,
            "conversation_id": conversation_id,
            "user_id": request.user_id,
            "mode": mode,
            "branch": request.branch,
            "objective": objective,
            "status": result.status,
            "reply": result.reply,
            "checks": checks,
            "logs": result.logs,
            "model_requested": request.use_model,
            "model_used": model_used,
            "rollback_recommended": rollback_recommended,
        }
    )
