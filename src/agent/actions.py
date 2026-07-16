"""Single Autonomous orchestrator for all Amosclaud entry points."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.foundation import AgentsPracticeStation, IntelligentFoundation
from src.services.code_analyzer import CodeAnalyzer
from src.services.file_manager import SafeFileManager
from src.services.runtime_exec import RuntimeExecutor

from .engineering_loop import AutonomousEngineeringLoop, LoopOutcome
from .model import AutonomousModelGateway
from .observations import Observation
from .react_loop import AutonomousReactLoop, ReactOutcome
from .react_tools import build_react_registry
from .reasoning import ActionRequest, ReactDecision


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

    @staticmethod
    def _react_execution_required(task: AutonomousTask) -> bool:
        return task.mode.lower() not in {"answer", "guide", "plan", "explain"}

    def _react_decision_provider(self, task: AutonomousTask):
        execution_required = self._react_execution_required(task)

        def decide(
            objective: str,
            observations: list[Observation],
            step: int,
        ) -> ReactDecision:
            del step
            if not observations:
                if not execution_required:
                    return ReactDecision(
                        kind="finish",
                        reason="Guidance request does not require tool execution.",
                        answer=(
                            f"Amosclaud Autonomous understood: {objective}. "
                            "A safe plan can be prepared without modifying the workspace."
                        ),
                    )
                return ReactDecision(
                    kind="act",
                    reason="Inspect repository evidence before taking further action.",
                    action=ActionRequest(
                        tool="inspect_repository",
                        purpose="Establish verified repository context.",
                    ),
                )

            latest = observations[-1]
            if not latest.success:
                return ReactDecision(
                    kind="blocked",
                    reason=latest.summary,
                    answer="The mission stopped because verified evidence failed.",
                )

            if not any(item.tool == "verify_runtime" for item in observations):
                return ReactDecision(
                    kind="act",
                    reason="Verify the current workspace before reporting success.",
                    action=ActionRequest(
                        tool="verify_runtime",
                        purpose="Produce compile and test evidence.",
                    ),
                )

            return ReactDecision(
                kind="finish",
                reason="Required evidence was collected and verified.",
                answer=(
                    "Amosclaud Autonomous completed the governed ReAct cycle: "
                    "reason, act, observe, and verify."
                ),
            )

        return decide

    def run_react(self, task: AutonomousTask) -> ReactOutcome:
        """Run ReAct as a governed engine beneath the main Autonomous."""
        registry = build_react_registry(self.workspace)
        react = AutonomousReactLoop(
            registry,
            self._react_decision_provider(task),
            max_steps=int(task.metadata.get("react_max_steps", 8)),
        )
        return react.run(
            task.objective,
            authorized_writes=task.authorized_writes,
            execution_required=self._react_execution_required(task),
        )

    def run(self, task: AutonomousTask) -> LoopOutcome | ReactOutcome:
        if task.mode.lower() == "react" or bool(task.metadata.get("use_react")):
            return self.run_react(task)

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
            authorized_writes=(
                task.authorized_writes and "write" in context.allowed_actions
            ),
        )
        practice = self.practice_station.practice(
            context.next_lesson["level"],
            verifier=lambda: outcome.checks
            or [
                {
                    "name": "engineering-loop",
                    "passed": outcome.status == "success",
                    "summary": "Engineering loop completed truthfully.",
                }
            ],
            evidence=[event.message for event in outcome.events],
        )
        outcome.lessons.extend(
            [
                f"Foundation confidence: {context.confidence}; risk: {context.risk}.",
                (
                    f"Practice Station: {practice.lesson}; score {practice.score}; "
                    f"status {practice.status}."
                ),
            ]
        )
        self.foundation.memory.remember(
            "project",
            (
                f"Objective: {task.objective}; outcome: {outcome.status}; "
                f"practice: {practice.status}"
            ),
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
