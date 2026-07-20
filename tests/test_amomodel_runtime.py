from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from amomodel.runtime import AmoModelRuntime
from amoscloud_ai.main import create_app
from database.models import AutonomousJob, CIPipeline, CIStatus, Repository, UserProfile
from database.session import create_database, session_scope


def test_amomodel_routes_are_registered():
    paths = {getattr(route, "path", "") for route in create_app().routes}
    assert "/api/v1/amomodel/status" in paths
    assert "/api/v1/amomodel/power/on" in paths
    assert "/api/v1/amomodel/power/off" in paths
    assert "/api/v1/amomodel/restart" in paths
    assert "/api/v1/amomodel/execute" in paths
    assert "/api/v1/amomodel/jobs/{task_id}" in paths


def test_amomodel_persists_truthful_lifecycle(tmp_path: Path):
    state_path = tmp_path / "state.json"
    runtime = AmoModelRuntime(state_path)

    assert runtime.status()["state"] == "off"
    ready = runtime.power_on("tester")
    assert ready["state"] == "ready"
    assert ready["healthy"] is True
    assert "autonomous-job-scheduling" in ready["capabilities"]
    assert ready["services"]["shared-database"] == "ready"
    assert ready["services"]["autonomous-worker"] == "ready"

    executed = runtime.execute("tester", "Inspect platform readiness")
    assert executed["accepted"] is True
    assert executed["status"] == "planned"
    assert executed["runtime"]["executions"] == 1

    reloaded = AmoModelRuntime(state_path).status()
    assert reloaded["state"] == "ready"
    assert reloaded["executions"] == 1
    assert reloaded["audit"]

    stopped = runtime.power_off("tester")
    assert stopped["state"] == "off"
    assert all(value == "off" for value in stopped["services"].values())


def test_amomodel_queues_database_backed_autonomous_job(tmp_path: Path):
    create_database()
    suffix = uuid4().hex
    with session_scope() as session:
        user = UserProfile(username=f"amo-{suffix}", email=f"amo-{suffix}@example.test")
        session.add(user)
        session.flush()
        repository = Repository(name=f"repo-{suffix}", owner_id=user.id)
        session.add(repository)
        session.flush()
        repository_id = repository.id
        user_id = user.id

    runtime = AmoModelRuntime(tmp_path / "state.json")
    runtime.power_on("tester")
    result = runtime.execute(
        "tester",
        "Repair the failing repository test",
        repository_id=repository_id,
        requested_by_id=user_id,
        mode="fix",
        target_file="tests/test_example.py",
        error_context="one test failed",
        commit_sha="abc123",
    )

    assert result["status"] == "queued"
    assert result["agent_type"] == "amosclaud-fixer"
    assert result["verification_required"] is True
    status = runtime.job_status(result["task_id"])
    assert status["status"] == "queued"
    assert status["ci_status"] == "pending"
    assert status["verification_id"] is None

    with session_scope() as session:
        job = session.scalar(select(AutonomousJob).where(AutonomousJob.task_id == result["task_id"]))
        assert job is not None
        assert job.repository_id == repository_id
        assert job.target_file == "tests/test_example.py"
        pipeline = session.get(CIPipeline, result["ci_pipeline_id"])
        assert pipeline is not None
        assert pipeline.status is CIStatus.PENDING
        assert pipeline.verification_id is None
        owner = session.get(UserProfile, user_id)
        session.delete(owner)


def test_amomodel_never_accepts_empty_objective(tmp_path: Path):
    runtime = AmoModelRuntime(tmp_path / "state.json")
    runtime.power_on("tester")
    try:
        runtime.execute("tester", "   ")
    except ValueError as exc:
        assert "objective" in str(exc)
    else:
        raise AssertionError("empty objective must be rejected")


def test_dashboard_exposes_amomodel_power_controls():
    html = Path("web/index.html").read_text(encoding="utf-8")
    script = Path("web/amomodel-controls.js").read_text(encoding="utf-8")
    assert "Turn on AmoModel" in html
    assert "Turn off AmoModel" in html
    assert "/api/v1/amomodel/status" in script
    assert "/api/v1/amomodel/power/on" in script
    assert "/api/v1/amomodel/power/off" in script
