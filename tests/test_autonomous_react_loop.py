from pathlib import Path

from src.agent.action_policy import ActionPolicy
from src.agent.observations import Observation
from src.agent.react_integration import AutonomousReactController
from src.agent.react_loop import AutonomousReactLoop
from src.agent.reasoning import ActionRequest, ReactDecision
from src.agent.tool_registry import ToolDefinition, ToolRegistry


def test_policy_blocks_unauthorized_write_tool() -> None:
    policy = ActionPolicy(
        authorized_writes=False,
        allowed_tools=frozenset({"write_file"}),
        write_tools=frozenset({"write_file"}),
    )
    allowed, reason = policy.authorize("write_file")
    assert allowed is False
    assert "write authorization" in reason


def test_react_requires_evidence_before_execution_success() -> None:
    registry = ToolRegistry()

    def decide(
        objective: str,
        observations: list[Observation],
        step: int,
    ) -> ReactDecision:
        del objective, observations, step
        return ReactDecision(kind="finish", reason="done", answer="complete")

    outcome = AutonomousReactLoop(registry, decide).run(
        "execute a task",
        execution_required=True,
    )
    assert outcome.status == "failed"
    assert outcome.verification is not None
    assert outcome.verification.passed is False


def test_react_executes_registered_tool_and_verifies() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="inspect",
            handler=lambda arguments: Observation(
                tool="inspect",
                success=True,
                summary=str(arguments["summary"]),
            ),
        )
    )

    def decide(
        objective: str,
        observations: list[Observation],
        step: int,
    ) -> ReactDecision:
        del objective, step
        if not observations:
            return ReactDecision(
                kind="act",
                reason="inspect first",
                action=ActionRequest(
                    tool="inspect",
                    arguments={"summary": "verified"},
                ),
            )
        return ReactDecision(kind="finish", reason="verified", answer="complete")

    outcome = AutonomousReactLoop(registry, decide).run("inspect repository")
    assert outcome.status == "success"
    assert outcome.steps == 2
    assert outcome.observations[0].summary == "verified"


def test_controller_inspects_real_workspace(tmp_path: Path) -> None:
    (tmp_path / "example.py").write_text("value = 1\n", encoding="utf-8")
    outcome = AutonomousReactController(tmp_path).run("inspect the workspace")
    assert outcome.status == "success"
    assert outcome.observations[0].tool == "inspect_workspace"
    assert "AST parse failures: 0" in outcome.observations[0].evidence
