from pathlib import Path
from src.agent.operations_controller import AgentOperationsController


def test_job_tracking(tmp_path: Path):
    controller = AgentOperationsController(
        lambda **kwargs: {"status": "success", "changed_files": [], "checks": [], "events": [], "blocker": None},
        str(tmp_path / "ops.db"),
    )
    job = controller.submit("inspect project", mode="review")
    assert job["status"] == "completed"
    assert job["progress"] == 100
    assert job["agent"] == "agent-2-evidence"


def test_truthful_waiting_state(tmp_path: Path):
    controller = AgentOperationsController(
        lambda **kwargs: {"status": "failed", "changed_files": [], "checks": [], "events": [], "blocker": "Approval required"},
        str(tmp_path / "ops.db"),
    )
    job = controller.submit("update project", mode="fix", authorized_writes=False)
    assert job["status"] == "waiting_for_approval"
