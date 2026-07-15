"""One Autonomous orchestrator: perceive -> plan -> act -> verify -> report."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import monotonic
from typing import Any

from .model import AutonomousModelGateway
from src.services.code_analyzer import CodeAnalyzer
from src.services.file_manager import SafeFileManager
from src.services.runtime_exec import RuntimeExecutor


@dataclass
class AutonomousTask:
    objective: str
    mode: str = "plan"
    authorized_writes: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AutonomousResult:
    status: str
    objective: str
    plan: list[str]
    evidence: list[str]
    changed_files: list[str]
    checks: list[dict[str, Any]]
    duration_seconds: float
    blocker: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AutonomousOrchestrator:
    """The only entry point for all Amosclaud autonomous capabilities."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.model = AutonomousModelGateway()
        self.analyzer = CodeAnalyzer(self.workspace)
        self.files = SafeFileManager(self.workspace)
        self.runtime = RuntimeExecutor(self.workspace)

    def run(self, task: AutonomousTask) -> AutonomousResult:
        started = monotonic()
        evidence = self.analyzer.inspect()
        plan = self.model.plan(task.objective, evidence) if task.mode == "fix" else [
            "Understand objective",
            "Inspect verified evidence",
            "Run deterministic checks",
            "Report results",
        ]
        changed: list[str] = []

        if task.mode == "fix" and not task.authorized_writes:
            return AutonomousResult(
                status="blocked",
                objective=task.objective,
                plan=plan,
                evidence=evidence,
                changed_files=[],
                checks=[],
                duration_seconds=round(monotonic() - started, 3),
                blocker="File writes require explicit authorization",
            )

        checks = self.runtime.verify()
        failed = [item for item in checks if not item["passed"]]
        return AutonomousResult(
            status="failed" if failed else "success",
            objective=task.objective,
            plan=plan,
            evidence=evidence,
            changed_files=changed,
            checks=checks,
            duration_seconds=round(monotonic() - started, 3),
            blocker=failed[0]["summary"] if failed else None,
        )


def run_autonomous(objective: str, mode: str = "plan", authorized_writes: bool = False, workspace: str = ".") -> dict[str, Any]:
    """Public function used by UI, API, webhooks, jobs, and all internal engines."""
    task = AutonomousTask(objective=objective, mode=mode, authorized_writes=authorized_writes)
    return AutonomousOrchestrator(Path(workspace)).run(task).to_dict()
