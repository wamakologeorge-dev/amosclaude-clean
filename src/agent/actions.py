"""Single Autonomous orchestrator for all Amosclaud entry points."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .engineering_loop import AutonomousEngineeringLoop, LoopOutcome
from .model import AutonomousModelGateway
from src.foundation import AgentsPracticeStation, IntelligentFoundation
from src.services.code_analyzer import CodeAnalyzer
from src.services.file_manager import SafeFileManager
from src.services.runtime_exec import RuntimeExecutor


@dataclass
class AutonomousTask:
    objective: str
    mode: str = "plan"
    authorized_writes: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class AutonomousOrchestrator:
    """One intelligent coordinator for UI, API, webhooks, jobs, agents, and lessons."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.model = AutonomousModelGateway()
        self.analyzer = CodeAnalyzer(self.workspace)
        self.files = SafeFileManager(self.workspace)
        self.runtime = RuntimeExecutor(self.workspace)
        self.foundation = IntelligentFoundation(self.workspace)
        self.practice_station = AgentsPracticeStation(self.workspace)
        self.engineering_loop = AutonomousEngineeringLoop(
            analyzer=self.analyzer,
            model=self.model,
            files=self.files,
            runtime=self.runtime,
            max_attempts=2,
        )

    def run(self, task: AutonomousTask) -> LoopOutcome:
        level = int(task.metadata.get("academy_level", 1))
        founder_verified = bool(task.metadata.get("founder_verified", False))
        context = self.foundation.prepare(
            task.objective,
            authorized_writes=task.authorized_writes,
            founder_verified=founder_verified,
            current_level=level,
        )
        outcome = self.engineering_loop.run(
            objective=task.objective,
            mode=task.mode,
            authorized_writes=task.authorized_writes and "write" in context.allowed_actions,
        )
        practice = self.practice_station.practice(
            context.next_lesson["level"],
            verifier=lambda: outcome.checks or [
                {"name": "engineering-loop", "passed": outcome.status == "success", "summary": "Engineering loop completed truthfully."}
            ],
            evidence=[event.message for event in outcome.events],
        )
        outcome.lessons.extend(
            [
                f"Foundation confidence: {context.confidence}; risk: {context.risk}.",
                f"Practice Station: {practice.lesson}; score {practice.score}; status {practice.status}.",
            ]
        )
        self.foundation.memory.remember(
            "project",
            f"Objective: {task.objective}; outcome: {outcome.status}; practice: {practice.status}",
            evidence=" | ".join(outcome.lessons),
        )
        return outcome


def run_autonomous(
    objective: str,
    mode: str = "plan",
    authorized_writes: bool = False,
    workspace: str = ".",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task = AutonomousTask(
        objective=objective,
        mode=mode,
        authorized_writes=authorized_writes,
        metadata=dict(metadata or {}),
    )
    return AutonomousOrchestrator(Path(workspace)).run(task).to_dict()
