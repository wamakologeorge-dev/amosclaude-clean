"""Integration contract for root main.py and the shared platform database."""

from __future__ import annotations

from contextlib import contextmanager
import subprocess

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main as root_main
from database.models import (
    AutonomousJob,
    AutonomousJobStatus,
    Base,
    CIPipeline,
    CIStatus,
    Repository,
    UserProfile,
)


def test_guardrail_success_is_persisted_as_verified_platform_work(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def test_session_scope():
        session = testing_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(root_main, "create_database", lambda: None)
    monkeypatch.setattr(root_main, "session_scope", test_session_scope)

    with test_session_scope() as session:
        owner = UserProfile(username="george", email="george@example.test")
        repository = Repository(name="amosclaud", owner=owner)
        session.add(repository)
        session.flush()
        pipeline = CIPipeline(
            repository_id=repository.id,
            commit_sha="a" * 40,
            status=CIStatus.PENDING,
        )
        session.add(pipeline)
        session.flush()
        repository_id = repository.id
        pipeline_id = pipeline.id

    orchestrator = root_main.AmosclaudEngine(
        task_id="root-database-test",
        repository_id=repository_id,
        ci_pipeline_id=pipeline_id,
    )
    monkeypatch.setattr(
        orchestrator,
        "_run",
        lambda command: subprocess.CompletedProcess(command, 0, stdout="", stderr=""),
    )

    assert orchestrator.run_guardrails() is True

    with test_session_scope() as session:
        job = session.query(AutonomousJob).filter_by(task_id="root-database-test").one()
        pipeline = session.get(CIPipeline, pipeline_id)

        assert job.repository_id == repository_id
        assert job.ci_pipeline_id == pipeline_id
        assert job.status == AutonomousJobStatus.PASSED
        assert "verification passed" in job.result_summary.lower()
        assert pipeline.status == CIStatus.PASSED
        assert pipeline.verification_id
        assert pipeline.completed_at is not None


def test_root_main_exports_the_real_platform_app():
    paths = {getattr(route, "path", "") for route in root_main.app.routes}
    assert "/health" in paths
    assert "/api/v1/agent/run" in paths
