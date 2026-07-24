"""Integration contract for gateway + database + Autonomous repository teamwork."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database.models import (
    AutonomousJob,
    AutonomousJobStatus,
    Base,
    CIPipeline,
    CIStatus,
    PRStatus,
    PullRequest,
    Repository,
    UserProfile,
)


def test_database_models_form_one_autonomous_repository_team() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user = UserProfile(username="george", email="george@example.com")
        repository = Repository(name="amosclaud-app", owner=user, default_branch="main")
        pull_request = PullRequest(
            repository=repository,
            creator=user,
            title="Autonomous repair",
            source_branch="repair/routes",
            target_branch="main",
            status=PRStatus.OPEN,
        )
        pipeline = CIPipeline(
            repository=repository,
            pull_request=pull_request,
            commit_sha="a" * 40,
            status=CIStatus.RUNNING,
        )
        job = AutonomousJob(
            task_id="repair-434",
            agent_type="amosclaud-fixer",
            repository=repository,
            pull_request=pull_request,
            ci_pipeline=pipeline,
            requested_by=user,
            objective="Fix failing route registration tests",
            status=AutonomousJobStatus.VERIFYING,
        )
        session.add(job)
        session.commit()

        stored = session.query(AutonomousJob).filter_by(task_id="repair-434").one()
        assert stored.repository.owner.username == "george"
        assert stored.pull_request.status is PRStatus.OPEN
        assert stored.ci_pipeline.status is CIStatus.RUNNING
        assert stored.agent_type == "amosclaud-fixer"


def test_gateway_uses_shared_database_and_never_claims_unverified_success() -> None:
    source = Path("api-gateway/main.py").read_text(encoding="utf-8")

    assert "from database.models import AutonomousJob" in source
    assert "create_database()" in source
    assert 'status_code=status.HTTP_202_ACCEPTED' in source
    assert "AutonomousJobStatus.QUEUED" in source
    assert '"status": "remediated"' not in source
    assert "settings.SERVICE_A_URL" in source
    assert "settings.SERVICE_B_URL" in source
    assert "settings.SERVICE_C_URL" in source


def test_gateway_has_one_route_for_each_platform_team() -> None:
    source = Path("api-gateway/main.py").read_text(encoding="utf-8")

    assert '/api/repository/{path:path}' in source
    assert '/api/autonomous/{path:path}' in source
    assert '/api/ci/{path:path}' in source
    assert '/api/agent/jobs/{task_id}' in source
