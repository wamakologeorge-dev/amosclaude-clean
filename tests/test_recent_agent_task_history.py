from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from amoscloud_ai.api.routes import pr_tasks
from amoscloud_ai.main import create_app
from amoscloud_ai.models import RepositoryTaskResponse, RepositoryTaskStatus


def _task(task_id: str, created_at: datetime, status: RepositoryTaskStatus) -> RepositoryTaskResponse:
    return RepositoryTaskResponse(
        task_id=task_id,
        status=status,
        objective=f"Objective {task_id}",
        branch=f"amosclaud/agent-{task_id}",
        message=status.value,
        created_at=created_at,
        updated_at=created_at,
        pull_request_url=None,
        logs=["queued"],
    )


def test_recent_tasks_are_returned_newest_first(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_TASK_DB_PATH", str(tmp_path / "agent_tasks.db"))
    pr_tasks._tasks.clear()
    now = datetime.now(timezone.utc)

    pr_tasks._persist_task(_task("older", now - timedelta(minutes=2), RepositoryTaskStatus.COMPLETED))
    pr_tasks._persist_task(_task("newer", now - timedelta(minutes=1), RepositoryTaskStatus.FAILED))

    tasks = pr_tasks.list_recent_tasks(limit=10)

    assert [task.task_id for task in tasks] == ["newer", "older"]


def test_history_route_accepts_owner_key_and_honors_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_TASK_DB_PATH", str(tmp_path / "agent_tasks.db"))
    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "owner-secret")
    pr_tasks._tasks.clear()
    now = datetime.now(timezone.utc)

    pr_tasks._persist_task(_task("one", now - timedelta(minutes=3), RepositoryTaskStatus.COMPLETED))
    pr_tasks._persist_task(_task("two", now - timedelta(minutes=2), RepositoryTaskStatus.COMPLETED))
    pr_tasks._persist_task(_task("three", now - timedelta(minutes=1), RepositoryTaskStatus.COMPLETED))

    with TestClient(create_app()) as client:
        response = client.get(
            "/api/v1/agent/github/history?limit=2",
            headers={"X-Amosclaud-Owner-Key": "owner-secret"},
        )

    assert response.status_code == 200
    assert [item["task_id"] for item in response.json()] == ["three", "two"]


def test_history_route_rejects_unauthorised_requests(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_TASK_DB_PATH", str(tmp_path / "agent_tasks.db"))
    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "owner-secret")
    pr_tasks._tasks.clear()

    with TestClient(create_app()) as client:
        response = client.get("/api/v1/agent/github/history")

    assert response.status_code == 401
