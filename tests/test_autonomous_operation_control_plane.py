from __future__ import annotations

import sqlite3
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from amoscloud_ai import cloud_task_runner, github_relay_recovery


class _CheckRuntime:
    seen: list[str] | None = None

    def __init__(self, workspace: Path):
        self.workspace = workspace

    def verify(self, changed_files=None):
        type(self).seen = list(changed_files or [])
        return [
            {
                "name": "Focused pytest",
                "command": "python -m pytest -q tests/test_widget.py",
                "passed": True,
                "summary": "1 passed",
                "output": "1 passed",
                "isolated": True,
            }
        ]


class _FailedRuntime(_CheckRuntime):
    def verify(self, changed_files=None):
        return [
            {
                "name": "Frontend build",
                "command": "npm run build",
                "passed": False,
                "summary": "TypeScript compiler failed",
                "output": "src/app.ts(3,4): error TS2322",
                "isolated": True,
            }
        ]


def test_cloud_verification_routes_changed_files_to_isolated_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cloud_task_runner, "RuntimeExecutor", _CheckRuntime)

    evidence, checks = cloud_task_runner._run_verification(
        tmp_path, ["src/widget.py", "tests/test_widget.py"]
    )

    assert _CheckRuntime.seen == ["src/widget.py", "tests/test_widget.py"]
    assert checks[0]["isolated"] is True
    assert "Focused pytest: passed" in evidence[0]


def test_failed_isolated_check_blocks_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cloud_task_runner, "RuntimeExecutor", _FailedRuntime)

    with pytest.raises(RuntimeError, match="Isolated repository verification failed"):
        cloud_task_runner._run_verification(tmp_path, ["src/app.ts"])


def test_production_dispatch_stays_queued_when_celery_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deferred: list[tuple[str, str]] = []
    monkeypatch.setattr(cloud_task_runner, "_production", lambda: True)
    monkeypatch.setattr(
        cloud_task_runner,
        "_record_dispatch_deferred",
        lambda task_id, exc: deferred.append((task_id, type(exc).__name__)),
    )

    dispatch_module = types.ModuleType("amoscloud_ai.task_dispatch")

    def _unavailable(*_args, **_kwargs):
        raise ConnectionError("broker unavailable")

    dispatch_module.dispatch_task = _unavailable
    worker_module = types.ModuleType("amoscloud_ai.worker")
    worker_module.run_global_task = object()
    monkeypatch.setitem(sys.modules, "amoscloud_ai.task_dispatch", dispatch_module)
    monkeypatch.setitem(sys.modules, "amoscloud_ai.worker", worker_module)

    cloud_task_runner.dispatch_cloud_task("task_123")

    assert deferred == [("task_123", "ConnectionError")]


def test_recovery_requeues_stale_running_tasks_and_redispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE global_tasks (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            execution_target TEXT NOT NULL,
            started_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE global_task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            event_type TEXT,
            message TEXT,
            details_json TEXT,
            created_at TEXT
        );
        """
    )
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    db.executemany(
        "INSERT INTO global_tasks VALUES (?,?,?,?,?)",
        [
            ("task_queued", "queued", "github", None, now),
            ("task_stale", "running", "cloud", old, old),
            ("task_live", "running", "github", now, now),
        ],
    )
    db.commit()

    class _Connection:
        def __enter__(self):
            return db

        def __exit__(self, *_args):
            return False

    events: list[tuple[str, str]] = []
    dispatched: list[str] = []
    monkeypatch.setattr(cloud_task_runner, "_connect", lambda: _Connection())
    monkeypatch.setattr(cloud_task_runner, "_ensure_schema", lambda _db: None)
    monkeypatch.setattr(
        cloud_task_runner,
        "_event",
        lambda _db, task_id, event_type, *_args, **_kwargs: events.append(
            (task_id, event_type)
        ),
    )
    monkeypatch.setattr(
        cloud_task_runner, "dispatch_cloud_task", lambda task_id: dispatched.append(task_id)
    )

    result = cloud_task_runner.recover_cloud_tasks(stale_seconds=300)

    assert result == {"recovered": 1, "dispatched": 2}
    assert set(dispatched) == {"task_queued", "task_stale"}
    assert ("task_stale", "task.recovered") in events
    status = db.execute(
        "SELECT status,started_at FROM global_tasks WHERE id='task_stale'"
    ).fetchone()
    assert status["status"] == "queued" and status["started_at"] is None


def test_pending_issue_relay_is_retried_in_place(monkeypatch: pytest.MonkeyPatch) -> None:
    row = {
        "id": "relay_1",
        "command_id": "command_1",
        "repository": "owner/repo",
        "issue_number": 9,
        "body": "verification complete",
    }

    class _Cursor:
        def fetchall(self):
            return [row]

    class _DB:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            return _Cursor()

    states: list[tuple[str, str]] = []
    commands = github_relay_recovery.github_issue_commands
    monkeypatch.setattr(commands, "_commands_db", lambda: _DB())
    monkeypatch.setattr(commands, "_record", lambda _id: {"account_id": 4})
    monkeypatch.setattr(commands, "_relay_token", lambda _id: "token")
    monkeypatch.setattr(
        commands,
        "_post_comment",
        lambda repository, issue_number, body, token: (
            repository == "owner/repo"
            and issue_number == 9
            and body == "verification complete"
            and token == "token",
            "comment-url",
        ),
    )
    monkeypatch.setattr(
        commands,
        "_set_relay_state",
        lambda relay_id, state, detail: states.append((relay_id, state)),
    )

    result = github_relay_recovery.retry_pending_relays()

    assert result == {"attempted": 1, "delivered": 1, "pending": 0}
    assert states == [("relay_1", "delivered")]


def test_control_plane_source_has_no_host_subprocess_fallback() -> None:
    source = Path(cloud_task_runner.__file__).read_text(encoding="utf-8")
    assert "subprocess.run" not in source
    assert "RuntimeExecutor" in source
    assert '"draft": True' in source
    assert "_assert_base_unchanged" in source
    assert "task.dispatch_deferred" in source
