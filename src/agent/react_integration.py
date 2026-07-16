"""Production-safe ReAct integration for the single Amosclaud Autonomous."""
from __future__ import annotations

from pathlib import Path

from .observations import Observation
from .react_loop import AutonomousReactLoop, ReactOutcome
from .reasoning import ActionRequest, ReactDecision
from .tool_registry import ToolDefinition, ToolRegistry
from src.services.code_analyzer import CodeAnalyzer


class AutonomousReactController:
    """Build and run the governed ReAct engine beneath the main orchestrator."""

    def __init__(self, workspace: Path, *, max_steps: int = 6) -> None:
        self.workspace = workspace.resolve()
        self.analyzer = CodeAnalyzer(self.workspace)
        self.registry = ToolRegistry()
        self.registry.register(
            ToolDefinition(
                name="inspect_workspace",
                description="Collect repository structure and Python syntax evidence.",
                handler=self._inspect_workspace,
            )
        )
        self.max_steps = max_steps

    def _inspect_workspace(self, arguments: dict[str, object]) -> Observation:
        del arguments
        evidence = tuple(self.analyzer.inspect())
        failures = [item for item in evidence if item != "AST parse failures: 0" and item.startswith("AST parse failures:")]
        return Observation(
            tool="inspect_workspace",
            success=not failures,
            summary="Workspace inspection completed." if not failures else failures[0],
            evidence=evidence,
        )

    @staticmethod
    def _decision_provider(
        objective: str,
        observations: list[Observation],
        step: int,
    ) -> ReactDecision:
        del step
        if not observations:
            return ReactDecision(
                kind="act",
                reason="Inspect verified workspace evidence before deciding completion.",
                action=ActionRequest(
                    tool="inspect_workspace",
                    purpose=f"Establish evidence for objective: {objective}",
                ),
            )
        latest = observations[-1]
        if not latest.success:
            return ReactDecision(
                kind="blocked",
                reason=latest.summary,
                answer="The task is blocked by failed workspace evidence.",
            )
        return ReactDecision(
            kind="finish",
            reason="The required inspection evidence is successful.",
            answer="ReAct inspection completed with verified workspace evidence.",
        )

    def run(
        self,
        objective: str,
        *,
        authorized_writes: bool = False,
        execution_required: bool = True,
    ) -> ReactOutcome:
        loop = AutonomousReactLoop(
            registry=self.registry,
            decision_provider=self._decision_provider,
            max_steps=self.max_steps,
        )
        return loop.run(
            objective,
            authorized_writes=authorized_writes,
            execution_required=execution_required,
        )
