from datetime import datetime, timezone

from amoscloud_ai.api.routes import pr_tasks
from amoscloud_ai.models import RepositoryTaskResponse, RepositoryTaskStatus


def _sample_task() -> RepositoryTaskResponse:
    now = datetime.now(timezone.utc)
    return RepositoryTaskResponse(
        task_id="persistent-task-1",
        status=RepositoryTaskStatus.COMPLETED,
        objective="Verify persisted status",
        branch="amosclaud/agent-persist1",
        message="Completed and opened a pull request.",
        created_at=now,
        updated_at=now,
        pull_request_url="https://github.com/wamakologeorge-dev/amosclaude-clean/pull/999",
        logs=["clone", "test", "push"],
    )


def test_task_status_survives_memory_cache_loss(tmp_path, monkeypatch):
    database = tmp_path / "agent_tasks.db"
    monkeypatch.setenv("AGENT_TASK_DB_PATH", str(database))
    pr_tasks._tasks.clear()

    task = _sample_task()
    pr_tasks._persist_task(task)
    pr_tasks._tasks.clear()

    restored = pr_tasks.get_task_status(task.task_id)

    assert restored.status == RepositoryTaskStatus.COMPLETED
    assert restored.objective == task.objective
    assert restored.pull_request_url == task.pull_request_url
    assert restored.logs == ["clone", "test", "push"]
    assert database.is_file()


def test_persisted_task_updates_replace_previous_state(tmp_path, monkeypatch):
    database = tmp_path / "agent_tasks.db"
    monkeypatch.setenv("AGENT_TASK_DB_PATH", str(database))
    pr_tasks._tasks.clear()

    task = _sample_task()
    task.status = RepositoryTaskStatus.RUNNING
    task.message = "Running"
    pr_tasks._persist_task(task)

    task.status = RepositoryTaskStatus.FAILED
    task.message = "Failed safely"
    task.logs.append("Agent execution failed: RuntimeError")
    pr_tasks._persist_task(task)
    pr_tasks._tasks.clear()

    restored = pr_tasks.get_task_status(task.task_id)

    assert restored.status == RepositoryTaskStatus.FAILED
    assert restored.message == "Failed safely"
    assert restored.logs[-1] == "Agent execution failed: RuntimeError"
