from pathlib import Path

from src.agent.actions import AutonomousOrchestrator, AutonomousTask


def test_all_modes_use_one_orchestrator(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "sample.py").write_text("value = 1\n", encoding="utf-8")
    orchestrator = AutonomousOrchestrator(tmp_path)
    result = orchestrator.run(AutonomousTask(objective="Inspect project", mode="plan"))
    assert result.objective == "Inspect project"
    assert result.plan
    assert result.status in {"success", "failed"}


def test_fix_requires_write_authorization(tmp_path: Path):
    (tmp_path / "src").mkdir()
    orchestrator = AutonomousOrchestrator(tmp_path)
    result = orchestrator.run(AutonomousTask(objective="Fix issue", mode="fix", authorized_writes=False))
    assert result.status == "blocked"
    assert "authorization" in (result.blocker or "").lower()
