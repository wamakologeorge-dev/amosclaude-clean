from __future__ import annotations

import time
import uuid

import pytest

from Amosclaud.byte.core import ByteFrame
from Amosclaud.platform_bus import PlatformByteBus, signed_frame
from database.models import (
    AutonomousJob,
    AutonomousJobStatus,
    CIPipeline,
    CIStatus,
    Repository,
    UserProfile,
)
from database.session import create_database, session_scope


def _seed_team() -> tuple[int, int, str]:
    suffix = uuid.uuid4().hex[:10]
    task_id = f"bus-{suffix}"
    with session_scope() as session:
        user = UserProfile(username=f"bus-{suffix}", email=f"bus-{suffix}@example.test")
        session.add(user)
        session.flush()
        repository = Repository(name=f"repo-{suffix}", owner_id=user.id, default_branch="main")
        session.add(repository)
        session.flush()
        pipeline = CIPipeline(repository_id=repository.id, commit_sha=uuid.uuid4().hex, status=CIStatus.PENDING)
        session.add(pipeline)
        session.flush()
        job = AutonomousJob(
            task_id=task_id,
            agent_type="amosclaud-fixer",
            repository_id=repository.id,
            ci_pipeline_id=pipeline.id,
            objective="Repair and verify the repository",
            status=AutonomousJobStatus.QUEUED,
        )
        session.add(job)
        session.flush()
        return repository.id, pipeline.id, task_id


def test_platform_bus_connects_repository_job_and_ci() -> None:
    create_database()
    repository_id, pipeline_id, task_id = _seed_team()
    bus = PlatformByteBus(b"test-platform-secret")

    summary = bus.execute(bus.frame("platform.repository.summary", {"repository_id": repository_id})).json()
    assert summary["repository_id"] == repository_id
    assert summary["autonomous_jobs"] == 1
    assert summary["ci_pipelines"] == 1

    inspecting = bus.execute(
        bus.frame(
            "platform.job.transition",
            {"task_id": task_id, "status": "inspecting", "result_summary": "Inspecting failure evidence"},
        )
    ).json()
    assert inspecting["status"] == "inspecting"
    assert inspecting["ci_status"] == "running"

    bus.execute(bus.frame("platform.job.transition", {"task_id": task_id, "status": "repairing"}))
    bus.execute(bus.frame("platform.job.transition", {"task_id": task_id, "status": "verifying"}))
    passed = bus.execute(
        bus.frame(
            "platform.job.transition",
            {
                "task_id": task_id,
                "status": "passed",
                "verification_id": f"verify-{uuid.uuid4().hex}",
                "result_summary": "Compilation and tests passed",
            },
        )
    ).json()
    assert passed["status"] == "passed"
    assert passed["ci_status"] == "passed"
    assert passed["verification_id"].startswith("verify-")

    with session_scope() as session:
        job = session.query(AutonomousJob).filter_by(task_id=task_id).one()
        pipeline = session.get(CIPipeline, pipeline_id)
        assert job.status is AutonomousJobStatus.PASSED
        assert pipeline is not None
        assert pipeline.status is CIStatus.PASSED
        assert pipeline.verification_id == passed["verification_id"]
        assert pipeline.completed_at is not None


def test_platform_bus_rejects_replay_and_tampering() -> None:
    bus = PlatformByteBus(b"test-platform-secret")
    frame = bus.frame("platform.health", {})
    assert bus.execute(frame).json()["status"] == "ok"
    with pytest.raises(PermissionError, match="replayed"):
        bus.execute(frame)

    fresh = bus.frame("platform.health", {})
    altered = ByteFrame(
        route=fresh.route,
        payload=b'{"changed":true}',
        frame_id=fresh.frame_id,
        created_ns=fresh.created_ns,
        headers=fresh.headers,
    )
    with pytest.raises(PermissionError, match="signature"):
        bus.execute(altered)


def test_platform_bus_rejects_expired_and_unverified_success() -> None:
    repository_id, _pipeline_id, task_id = _seed_team()
    bus = PlatformByteBus(b"test-platform-secret")
    expired = signed_frame(
        "platform.repository.summary",
        {"repository_id": repository_id},
        secret=b"test-platform-secret",
        ttl_seconds=1,
        nonce="expired-test-nonce",
    )
    time.sleep(1.1)
    with pytest.raises(PermissionError, match="expired"):
        bus.execute(expired)

    bus.execute(bus.frame("platform.job.transition", {"task_id": task_id, "status": "inspecting"}))
    bus.execute(bus.frame("platform.job.transition", {"task_id": task_id, "status": "verifying"}))
    with pytest.raises(ValueError, match="verification_id"):
        bus.execute(bus.frame("platform.job.transition", {"task_id": task_id, "status": "passed"}))
