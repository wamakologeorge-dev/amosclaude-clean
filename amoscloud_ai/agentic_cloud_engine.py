"""Compatibility cloud-engine facade for Amosclaud Autonomous.

The former implementation ran a separate five-stage agent and could authorize
writes from request metadata.  The public types remain available, but the
canonical ``AutonomousKernel`` now owns planning, action, verification, and
write authorization.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.amosclaud_os.kernel import get_autonomous_kernel


ENGINE_NAMES = (
    "autonomous-receive",
    "autonomous-perceive",
    "autonomous-plan",
    "autonomous-act",
    "autonomous-verify",
)
LOG_SERVICE_NAMES = tuple(f"{name}-log" for name in ENGINE_NAMES)
ALLOWED_MODES = {"autonomous-check", "plan", "build", "fix", "deploy", "monitor"}
WRITE_MODES = {"build", "fix", "deploy"}


@dataclass
class AgentEvent:
    engine: str
    log_service: str
    status: str
    message: str
    evidence: list[str] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    duration_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "log_service": self.log_service,
            "status": self.status,
            "message": self.message,
            "evidence": self.evidence,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
        }


@dataclass
class AgenticCloudRun:
    run_id: str
    objective: str
    mode: str
    status: str
    summary: str
    authorized_writes: bool
    events: list[AgentEvent]
    changed_files: list[str] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    plan: list[str] = field(default_factory=list)
    memory: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "objective": self.objective,
            "mode": self.mode,
            "status": self.status,
            "summary": self.summary,
            "authorized_writes": self.authorized_writes,
            "plan": self.plan,
            "changed_files": self.changed_files,
            "checks": self.checks,
            "memory": self.memory,
            "events": [event.to_dict() for event in self.events],
        }


class StructuredModelLogService:
    """Compatibility no-op; kernel and platform audit services own logging."""

    def __init__(self, repository_root: Path, run_id: str) -> None:
        self.repository_root = repository_root.resolve()
        self.run_id = run_id

    def write(self, event: AgentEvent) -> None:
        return None


class AmosclaudAgenticCloudEngine:
    """Legacy facade that submits all work to Amosclaud Autonomous."""

    def __init__(self, repository_root: Path) -> None:
        self.root = repository_root.resolve()
        self.kernel = get_autonomous_kernel(self.root)

    def run(
        self,
        objective: str,
        mode: str,
        metadata: dict[str, Any] | None = None,
    ) -> AgenticCloudRun:
        metadata = dict(metadata or {})
        normalized_mode = (mode or "autonomous-check").strip().lower()
        if normalized_mode not in ALLOWED_MODES:
            raise ValueError(f"Unsupported agent mode: {normalized_mode}")
        objective = " ".join((objective or "").split())
        if not objective:
            raise ValueError("An autonomous objective is required")

        kernel_mode = "plan" if normalized_mode == "autonomous-check" else normalized_mode
        authorized_writes = bool(metadata.get("authorized_writes", False))
        result = self.kernel.execute(
            objective=objective,
            mode=kernel_mode,
            authorized_writes=authorized_writes,
            metadata={
                **metadata,
                "compatibility_entrypoint": "amoscloud_ai.agentic_cloud_engine",
            },
        )
        status = str(result.get("status") or "planned").lower()
        evidence = list(result.get("evidence") or [])
        event = AgentEvent(
            engine="amosclaud-autonomous-kernel",
            log_service="platform-audit",
            status=status,
            message=str(
                result.get("summary")
                or result.get("message")
                or result.get("error")
                or "Amosclaud Autonomous processed the request."
            ),
            evidence=evidence,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        raw_checks = result.get("checks") or result.get("tests") or []
        checks = [raw_checks] if isinstance(raw_checks, dict) else list(raw_checks)
        changed_files = [
            str(item.get("path") if isinstance(item, dict) else item)
            for item in (result.get("changed_files") or result.get("files_changed") or [])
            if item
        ]
        plan = [str(item) for item in (result.get("plan") or [])]
        return AgenticCloudRun(
            run_id=str(result.get("run_id") or result.get("verification_id") or uuid.uuid4().hex),
            objective=objective,
            mode=normalized_mode,
            status=status,
            summary=event.message,
            authorized_writes=authorized_writes,
            events=[event],
            changed_files=changed_files,
            checks=checks,
            plan=plan,
            memory=["Single runtime: src.amosclaud_os.kernel.AutonomousKernel"],
        )


__all__ = [
    "AgentEvent",
    "AgenticCloudRun",
    "AmosclaudAgenticCloudEngine",
    "StructuredModelLogService",
]
