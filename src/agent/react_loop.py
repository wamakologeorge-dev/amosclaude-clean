"""Governed Reason-Act-Observe-Verify loop for Amosclaud Autonomous."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from .action_policy import ActionPolicy
from .observations import Observation
from .reasoning import ReactDecision
from .tool_registry import ToolRegistry
from .verification import CompletionVerifier, VerificationResult

DecisionProvider = Callable[[str, list[Observation], int], ReactDecision]


@dataclass
class ReactOutcome:
    status: str
    answer: str
    steps: int
    observations: list[Observation] = field(default_factory=list)
    verification: VerificationResult | None = None
    blocker: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "answer": self.answer,
            "steps": self.steps,
            "observations": [item.to_dict() for item in self.observations],
            "verification": (
                None if self.verification is None else asdict(self.verification)
            ),
            "blocker": self.blocker,
        }


class AutonomousReactLoop:
    """Run bounded tool iterations under one Autonomous coordinator."""

    def __init__(
        self,
        registry: ToolRegistry,
        decision_provider: DecisionProvider,
        *,
        max_steps: int = 8,
        verifier: CompletionVerifier | None = None,
    ) -> None:
        if max_steps <= 0:
            raise ValueError("max_steps must be greater than zero")
        self.registry = registry
        self.decision_provider = decision_provider
        self.max_steps = max_steps
        self.verifier = verifier or CompletionVerifier()

    def run(
        self,
        objective: str,
        *,
        authorized_writes: bool = False,
        execution_required: bool = True,
    ) -> ReactOutcome:
        clean_objective = objective.strip()
        if not clean_objective:
            raise ValueError("objective must not be empty")

        observations: list[Observation] = []
        policy = ActionPolicy(
            authorized_writes=authorized_writes,
            allowed_tools=self.registry.names(),
            write_tools=self.registry.write_tools(),
        )

        for step in range(1, self.max_steps + 1):
            decision = self.decision_provider(clean_objective, observations, step)
            if decision.kind == "blocked":
                return ReactOutcome(
                    status="blocked",
                    answer=decision.answer,
                    steps=step,
                    observations=observations,
                    blocker=decision.reason,
                )
            if decision.kind == "finish":
                verification = self.verifier.verify(
                    observations,
                    execution_required=execution_required,
                )
                return ReactOutcome(
                    status="success" if verification.passed else "failed",
                    answer=decision.answer,
                    steps=step,
                    observations=observations,
                    verification=verification,
                    blocker="" if verification.passed else verification.summary,
                )

            action = decision.action
            if action is None:
                raise RuntimeError("act decision did not provide an action")
            allowed, reason = policy.authorize(action.tool)
            if not allowed:
                observations.append(
                    Observation(
                        tool=action.tool,
                        success=False,
                        summary=reason,
                    )
                )
                return ReactOutcome(
                    status="blocked",
                    answer="",
                    steps=step,
                    observations=observations,
                    blocker=reason,
                )
            observations.append(
                self.registry.execute(action.tool, action.arguments)
            )

        verification = self.verifier.verify(
            observations,
            execution_required=execution_required,
        )
        return ReactOutcome(
            status="failed",
            answer="",
            steps=self.max_steps,
            observations=observations,
            verification=verification,
            blocker="maximum ReAct steps reached before completion",
        )
