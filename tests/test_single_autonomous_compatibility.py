from pathlib import Path

from amoscloud_ai.agent import CodexAgent
from amoscloud_ai.agentic_cloud_engine import AmosclaudAgenticCloudEngine
from amoscloud_ai.engineering_agent import run_engineering_agent
from src.amosclaud_os.kernel import get_autonomous_kernel


def test_legacy_codex_agent_uses_canonical_kernel(tmp_path: Path) -> None:
    agent = CodexAgent(tmp_path)
    assert agent.kernel is get_autonomous_kernel(tmp_path)
    assert agent.provider == "amosclaud"
    code, stdout, stderr = agent.execute_local_command("echo unsafe")
    assert code == 2
    assert stdout == ""
    assert "Direct shell execution was removed" in stderr


def test_legacy_model_actions_are_not_executed(tmp_path: Path) -> None:
    agent = CodexAgent(tmp_path)
    result = agent.parse_and_execute_actions(
        '<write_file path="unsafe.py">print("unsafe")</write_file>'
    )
    assert result[0]["success"] is False
    assert not (tmp_path / "unsafe.py").exists()


def test_engineering_plan_uses_same_kernel(monkeypatch, tmp_path: Path) -> None:
    kernel = get_autonomous_kernel(tmp_path)
    monkeypatch.setattr(
        kernel,
        "execute",
        lambda **kwargs: {
            "status": "planned",
            "summary": "Plan prepared",
            "evidence": ["bounded"],
            "changed_files": ["app.py"],
        },
    )
    run = run_engineering_agent(tmp_path, "Inspect app.py")
    assert run.applied is False
    assert run.changes[0].status == "planned"
    assert any("AutonomousKernel" in item for item in run.evidence)


def test_cloud_engine_does_not_infer_write_authorization(tmp_path: Path) -> None:
    engine = AmosclaudAgenticCloudEngine(tmp_path)
    result = engine.run("Prepare a repair plan", "fix", {"apply_changes": True})
    assert result.authorized_writes is False
    assert result.status == "blocked"
    assert result.events[0].engine == "amosclaud-autonomous-kernel"
