"""Production-safe ReAct integration for the single Amosclaud Autonomous."""
from __future__ import annotations

from pathlib import Path

from src.services.code_analyzer import CodeAnalyzer
from src.services.runtime_exec import RuntimeExecutor

from .model import AutonomousModelGateway
from .observations import Observation
from .react_loop import AutonomousReactLoop, ReactOutcome
from .reasoning import ActionRequest, ReactDecision
from .tool_registry import ToolDefinition, ToolRegistry


class AutonomousReactController:
    """Build and run the governed ReAct engine beneath the main orchestrator."""

    def __init__(
        self,
        workspace: Path,
        *,
        max_steps: int = 6,
        model: AutonomousModelGateway | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.analyzer = CodeAnalyzer(self.workspace)
        self.runtime = RuntimeExecutor(self.workspace)
        self.model = model or AutonomousModelGateway()
        self.registry = ToolRegistry()
        self.registry.register(
            ToolDefinition(
                name="inspect_workspace",
                description="Collect repository structure and Python syntax evidence.",
                handler=self._inspect_workspace,
            )
        )
        self.registry.register(
            ToolDefinition(
                name="verify_runtime",
                description="Compile source files and run available repository tests.",
                handler=self._verify_runtime,
            )
        )
        self.max_steps = max_steps

    def _inspect_workspace(self, arguments: dict[str, object]) -> Observation:
        del arguments
        evidence = tuple(self.analyzer.inspect())
        failures = [
            item
            for item in evidence
            if item.startswith("AST parse failures:")
            and item != "AST parse failures: 0"
        ]
        return Observation(
            tool="inspect_workspace",
            success=not failures,
            summary=(
                "Workspace inspection completed." if not failures else failures[0]
            ),
            evidence=evidence,
        )

    def _verify_runtime(self, arguments: dict[str, object]) -> Observation:
        del arguments
        checks = self.runtime.verify()
        failures = [check for check in checks if not bool(check.get("passed"))]
        evidence = tuple(
            f"{check.get('command')}: {check.get('summary')}" for check in checks
        )
        return Observation(
            tool="verify_runtime",
            success=not failures,
            summary=(
                "Runtime verification completed."
                if not failures
                else f"{len(failures)} runtime check(s) failed."
            ),
            evidence=evidence,
            data={"checks": checks},
        )

    def _answer_from_model(
        self,
        objective: str,
        observations: list[Observation],
    ) -> str:
        evidence = [
            f"{item.tool}: {item.summary}; " + " | ".join(item.evidence)
            for item in observations
        ]
        if not self.model.available():
            return (
                "Amosclaud Autonomous completed inspection and runtime verification. "
                "The cloud model API is not configured, so the deterministic result "
                "is being returned without a generated model response."
            )
        return self.model.complete(objective, evidence)

    def _decision_provider(
        self,
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
                answer="The task is blocked by failed verified evidence.",
            )

        if not any(item.tool == "verify_runtime" for item in observations):
            return ReactDecision(
                kind="act",
                reason="Verify compilation and tests before reporting completion.",
                action=ActionRequest(
                    tool="verify_runtime",
                    purpose="Produce deterministic runtime evidence.",
                ),
            )

        try:
            answer = self._answer_from_model(objective, observations)
        except Exception as exc:
            return ReactDecision(
                kind="blocked",
                reason=f"Model API failure: {type(exc).__name__}: {exc}",
                answer="The verified tools completed, but the model API response failed.",
            )

        return ReactDecision(
            kind="finish",
            reason="Inspection and runtime evidence are verified.",
            answer=answer,
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
