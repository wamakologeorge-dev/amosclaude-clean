from pathlib import Path

from src.agent.actions import AutonomousOrchestrator, AutonomousTask
from src.agent.observations import Observation
from src.agent.react_loop import AutonomousReactLoop
from src.agent.reasoning import ActionRequest, ReactDecision
from src.agent.tool_registry import ToolDefinition, ToolRegistry


def test_react_loop_executes_and_verifies() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="inspect",
            handler=lambda _: Observation(
                tool="inspect",
                success=True,
                summary="inspection passed",
                evidence=("repository mapped",),
            ),
        )
    )

    def decide(objective, observations, step):
        assert objective == "inspect repository"
        if not observations:
            return ReactDecision(
                kind="act",
                reason="collect evidence",
                action=ActionRequest(tool="inspect"),
            )
        return ReactDecision(
            kind="finish",
            reason="evidence complete",
            answer="done",
        )

    outcome = AutonomousReactLoop(registry, decide).run("inspect repository")
    assert outcome.status == "success"
    assert outcome.answer == "done"
    assert outcome.verification is not None
    assert outcome.verification.passed is True
    assert len(outcome.observations) == 1


def test_react_loop_blocks_unauthorized_write() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="write",
            writes=True,
            handler=lambda _: Observation(
                tool="write",
                success=True,
                summary="written",
            ),
        )
    )

    def decide(objective, observations, step):
        del objective, observations, step
        return ReactDecision(
            kind="act",
            reason="attempt write",
            action=ActionRequest(tool="write"),
        )

    outcome = AutonomousReactLoop(registry, decide).run(
        "write file",
        authorized_writes=False,
    )
    assert outcome.status == "blocked"
    assert "write authorization" in outcome.blocker


def test_orchestrator_guidance_react_does_not_run_tools(tmp_path: Path) -> None:
    orchestrator = AutonomousOrchestrator(tmp_path)
    outcome = orchestrator.run(
        AutonomousTask(
            objective="Teach me how to code",
            mode="guide",
            metadata={"use_react": True},
        )
    )
    assert outcome.status == "success"
    assert outcome.observations == []
    assert "safe plan" in outcome.answer


def test_react_registry_inspects_and_verifies_small_workspace(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "example.py").write_text("value = 1\n", encoding="utf-8")
    orchestrator = AutonomousOrchestrator(tmp_path)
    outcome = orchestrator.run(
        AutonomousTask(
            objective="verify workspace",
            mode="react",
        )
    )
    assert outcome.status == "success"
    assert [item.tool for item in outcome.observations] == [
        "inspect_repository",
        "verify_runtime",
    ]
