from datetime import datetime, timedelta, timezone

from amoscloud_ai.api.routes import pr_tasks
from amoscloud_ai.models import RepositoryTaskResponse, RepositoryTaskStatus


def _task(status: RepositoryTaskStatus, updated_at: datetime) -> RepositoryTaskResponse:
    return RepositoryTaskResponse(
        task_id="stale-task-1",
        status=status,
        objective="Recover interrupted work",
        branch="amosclaud/agent-stale1",
        message="Working",
        created_at=updated_at - timedelta(minutes=5),
        updated_at=updated_at,
        pull_request_url=None,
        logs=["Task queued by authenticated owner."],
    )


def test_stale_running_task_is_marked_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_TASK_DB_PATH", str(tmp_path / "agent_tasks.db"))
    monkeypatch.setenv("AGENT_TASK_STALE_MINUTES", "10")
    pr_tasks._tasks.clear()

    task = _task(RepositoryTaskStatus.RUNNING, datetime.now(timezone.utc) - timedelta(minutes=11))
    pr_tasks._persist_task(task)

    restored = pr_tasks.get_task_status(task.task_id)

    assert restored.status == RepositoryTaskStatus.FAILED
    assert "interrupted" in restored.message.lower()
    assert restored.logs[-1] == "Task marked failed after exceeding the repository-agent stale timeout."

    pr_tasks._tasks.clear()
    persisted = pr_tasks.get_task_status(task.task_id)
    assert persisted.status == RepositoryTaskStatus.FAILED


def test_recent_running_task_remains_running(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_TASK_DB_PATH", str(tmp_path / "agent_tasks.db"))
    monkeypatch.setenv("AGENT_TASK_STALE_MINUTES", "10")
    pr_tasks._tasks.clear()

    task = _task(RepositoryTaskStatus.RUNNING, datetime.now(timezone.utc) - timedelta(minutes=2))
    pr_tasks._persist_task(task)

    restored = pr_tasks.get_task_status(task.task_id)

    assert restored.status == RepositoryTaskStatus.RUNNING
    assert restored.message == "Working"


def test_invalid_timeout_uses_safe_default(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_TASK_DB_PATH", str(tmp_path / "agent_tasks.db"))
    monkeypatch.setenv("AGENT_TASK_STALE_MINUTES", "invalid")
    pr_tasks._tasks.clear()

    task = _task(RepositoryTaskStatus.QUEUED, datetime.now(timezone.utc) - timedelta(minutes=61))
    pr_tasks._persist_task(task)

    restored = pr_tasks.get_task_status(task.task_id)

    assert restored.status == RepositoryTaskStatus.FAILED
