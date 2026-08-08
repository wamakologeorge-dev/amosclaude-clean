from __future__ import annotations

from pathlib import Path

import pytest

from amoscloud_ai.api.routes import auth
from amoscloud_ai.api.routes import pipeline_cooperation as cooperation


@pytest.fixture
def cooperation_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    database = tmp_path / "cooperation.db"
    monkeypatch.setattr(auth, "DB_PATH", database)
    return database


@pytest.fixture
def user() -> dict:
    return {"id": 41, "email": "owner@example.com", "is_admin": False}


def _register_worker(user: dict, name: str = "test-runner") -> dict:
    return cooperation.register_cooperation_worker(
        cooperation.CooperationWorkerRegister(
            name=name,
            capabilities=[
                "context",
                "repository-read",
                "planning",
                "repository-write",
                "testing",
                "security",
                "deployment",
                "observability",
                "verification",
            ],
            capacity=1,
        ),
        user=user,
    )


def _claim_and_complete(user: dict, worker: dict) -> dict:
    claimed = cooperation.claim_cooperation_task(worker["id"], user=user)["task"]
    assert claimed is not None
    return cooperation.complete_cooperation_task(
        claimed["id"],
        cooperation.CooperationTaskResult(
            worker_id=worker["id"],
            summary=f"Completed {claimed['task_key']}",
            output={"verified": True},
            artifacts=[
                {
                    "kind": "evidence",
                    "name": f"{claimed['task_key']}.json",
                    "uri": f"/artifacts/{claimed['id']}.json",
                }
            ],
        ),
        user=user,
    )


def test_inspection_pipeline_completes_through_capability_worker(
    cooperation_db: Path, user: dict
) -> None:
    pipeline = cooperation.create_cooperation_pipeline(
        cooperation.CooperationPipelineCreate(
            objective="Inspect the platform and return verified evidence.",
            mode="inspect",
            project_id="platform-workspace",
        ),
        user=user,
    )
    assert pipeline["state"] == "queued"
    assert [task["task_key"] for task in pipeline["tasks"]] == [
        "context",
        "inspect",
        "plan",
        "verify",
    ]
    assert pipeline["tasks"][0]["state"] == "queued"
    assert all(task["state"] == "blocked" for task in pipeline["tasks"][1:])

    worker = _register_worker(user)
    for _ in range(4):
        pipeline = _claim_and_complete(user, worker)

    assert pipeline["state"] == "completed"
    assert all(task["state"] == "completed" for task in pipeline["tasks"])
    assert len(pipeline["artifacts"]) == 4

    events = cooperation.cooperation_pipeline_events(pipeline["id"], after=0, limit=200, user=user)[
        "items"
    ]
    event_types = [event["event_type"] for event in events]
    assert event_types[0] == "pipeline.created"
    assert event_types.count("task.claimed") == 4
    assert event_types.count("task.completed") == 4
    assert "pipeline.completed" in event_types


def test_fix_pipeline_stops_at_write_gate_until_approved(cooperation_db: Path, user: dict) -> None:
    pipeline = cooperation.create_cooperation_pipeline(
        cooperation.CooperationPipelineCreate(
            objective="Fix the failing tests without bypassing repository policy.",
            mode="fix",
            project_id="platform-workspace",
            allow_writes=False,
        ),
        user=user,
    )
    worker = _register_worker(user)

    for expected_key in ("context", "inspect", "plan"):
        claimed = cooperation.claim_cooperation_task(worker["id"], user=user)["task"]
        assert claimed["task_key"] == expected_key
        pipeline = cooperation.complete_cooperation_task(
            claimed["id"],
            cooperation.CooperationTaskResult(
                worker_id=worker["id"], summary=f"Completed {expected_key}"
            ),
            user=user,
        )

    assert pipeline["state"] == "waiting_for_approval"
    implement = next(task for task in pipeline["tasks"] if task["task_key"] == "implement")
    assert implement["state"] == "blocked"
    assert pipeline["approvals"][0]["state"] == "pending"
    assert cooperation.claim_cooperation_task(worker["id"], user=user) == {"task": None}

    pipeline = cooperation.approve_cooperation_pipeline(
        pipeline["id"],
        cooperation.CooperationApprovalDecision(reason="Owner approved repository writes"),
        user=user,
    )
    implement = next(task for task in pipeline["tasks"] if task["task_key"] == "implement")
    assert pipeline["allow_writes"] is True
    assert pipeline["approvals"][0]["state"] == "approved"
    assert implement["state"] == "queued"


def test_control_plane_reports_all_twenty_modules(cooperation_db: Path) -> None:
    response = cooperation.control_plane_modules()
    keys = [module["key"] for module in response["modules"]]
    assert len(keys) == 20
    assert len(set(keys)) == 20
    assert {"agent", "ai_gateway", "sandboxes", "logs", "storage"}.issubset(keys)
