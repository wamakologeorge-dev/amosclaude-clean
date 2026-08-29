"""Focused contracts for fixed-plan, durable native Amosclaud Actions."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from git import Repo

from amoscloud_ai import native_actions
from amoscloud_ai.api.routes import repositories
from amoscloud_ai.isolated_runner import IsolatedRunResult
from amoscloud_ai.models import PipelineStatus


def _configure_store(tmp_path: Path, monkeypatch) -> Path:
    database = tmp_path / "auth.db"
    monkeypatch.setattr(repositories, "DB_PATH", database)
    # The legacy pipeline projection is mocked here; attribution is asserted
    # against the durable native_action_runs table itself.
    with repositories._db() as db:
        db.execute("PRAGMA foreign_keys = OFF")
        db.execute(
            "INSERT INTO repositories(id,owner_id,name,created_at,updated_at) VALUES (1,1,'demo','now','now')"
        )
        db.commit()
    return database


def _git_repository(tmp_path: Path, monkeypatch) -> tuple[Repo, str]:
    source = tmp_path / "repository"
    source.mkdir()
    repo = Repo.init(source)
    readme = source / "README.md"
    readme.write_text("native action\n", encoding="utf-8")
    repo.index.add([str(readme)])
    sha = repo.index.commit("initial action source").hexsha
    monkeypatch.setattr(native_actions, "_repo_path", lambda _repository_id: source)
    return repo, sha


def test_queue_failure_is_persisted_failed_not_falsely_queued(tmp_path, monkeypatch) -> None:
    database = _configure_store(tmp_path, monkeypatch)
    saved = {}
    monkeypatch.setattr(native_actions, "_pin_action_ref", lambda *_args: None)
    monkeypatch.setattr(native_actions.pipelines, "_save", lambda pipeline, *_args: saved.update({pipeline.id: pipeline}))
    monkeypatch.setattr(native_actions, "dispatch_task", lambda *_args: (_ for _ in ()).throw(OSError("broker down")))

    pipeline = native_actions.queue_action(
        repository_id=1,
        pull_request_id=7,
        branch="feature/test",
        head_sha="a" * 40,
        requested_by=1,
        reason="test",
    )

    assert pipeline.status is PipelineStatus.FAILED
    assert all(job.status is PipelineStatus.FAILED for job in pipeline.jobs)
    with sqlite3.connect(database) as db:
        row = db.execute("SELECT status,error_detail FROM native_action_runs WHERE id=?", (pipeline.id,)).fetchone()
    assert row[0] == "failed"
    assert "queue unavailable" in row[1].lower()


def test_database_failure_releases_unowned_pinned_ref(tmp_path, monkeypatch) -> None:
    _configure_store(tmp_path, monkeypatch)
    repo, sha = _git_repository(tmp_path, monkeypatch)
    monkeypatch.setattr(
        native_actions, "_ensure_schema", lambda _db: (_ for _ in ()).throw(sqlite3.OperationalError("write failed"))
    )

    try:
        native_actions.queue_action(
            repository_id=1, pull_request_id=7, branch="feature/test", head_sha=sha, requested_by=1, reason="test"
        )
    except sqlite3.OperationalError:
        pass
    else:
        raise AssertionError("database failure should surface to the route")

    assert repo.git.for_each_ref("--format=%(refname)", "refs/amosclaud/actions") == ""


def test_queue_pins_ref_persists_queued_state_and_removes_ref_after_terminal_result(tmp_path, monkeypatch) -> None:
    database = _configure_store(tmp_path, monkeypatch)
    repo, sha = _git_repository(tmp_path, monkeypatch)
    stored = {}
    monkeypatch.setattr(native_actions.pipelines, "_save", lambda pipeline, *_args: stored.update({pipeline.id: pipeline.model_copy(deep=True)}))
    monkeypatch.setattr(native_actions.pipelines, "_get", lambda action_id: stored.get(action_id))
    monkeypatch.setattr(native_actions, "dispatch_task", lambda *_args: None)
    monkeypatch.setattr(
        native_actions,
        "run_in_isolated_container",
        lambda *_args, **_kwargs: IsolatedRunResult(returncode=1, output="compile error"),
    )

    queued = native_actions.queue_action(
        repository_id=1, pull_request_id=8, branch="feature/test", head_sha=sha, requested_by=1, reason="test"
    )
    assert queued.status is PipelineStatus.QUEUED
    assert all(job.status is PipelineStatus.QUEUED for job in queued.jobs)
    with sqlite3.connect(database) as db:
        row = db.execute("SELECT status,action_ref FROM native_action_runs WHERE id=?", (queued.id,)).fetchone()
    assert row[0] == "queued"
    action_ref = row[1]
    assert repo.commit(action_ref).hexsha == sha

    result = native_actions.execute_action(queued.id)
    assert result is not None and result.status is PipelineStatus.FAILED
    try:
        repo.git.rev_parse("--verify", action_ref)
    except Exception:
        pass
    else:
        raise AssertionError("terminal native Action left its private ref behind")


def test_execute_claims_only_queued_row_and_uses_stored_action_ref(tmp_path, monkeypatch) -> None:
    database = _configure_store(tmp_path, monkeypatch)
    stored = {}
    checkout = tmp_path / "detached"
    checkout.mkdir()
    checkout_calls = []
    calls = []
    monkeypatch.setattr(native_actions, "_pin_action_ref", lambda *_args: None)
    monkeypatch.setattr(native_actions.pipelines, "_save", lambda pipeline, *_args: stored.update({pipeline.id: pipeline.model_copy(deep=True)}))
    monkeypatch.setattr(native_actions.pipelines, "_get", lambda action_id: stored.get(action_id))
    monkeypatch.setattr(native_actions, "dispatch_task", lambda *_args: None)
    monkeypatch.setattr(
        native_actions,
        "_detached_checkout",
        lambda repository_id, action_ref, sha: (checkout_calls.append((repository_id, action_ref, sha)) or (None, checkout, None, None)),
    )
    monkeypatch.setattr(native_actions, "_remove_checkout", lambda *_args: None)

    def failed_compile(command, **_kwargs):
        calls.append(command)
        return IsolatedRunResult(returncode=1, output="compile error")

    monkeypatch.setattr(native_actions, "run_in_isolated_container", failed_compile)
    queued = native_actions.queue_action(
        repository_id=1, pull_request_id=9, branch="feature/test", head_sha="b" * 40, requested_by=1, reason="test"
    )
    with sqlite3.connect(database) as db:
        action_ref = db.execute("SELECT action_ref FROM native_action_runs WHERE id=?", (queued.id,)).fetchone()[0]
    pipeline = native_actions.execute_action(queued.id)

    assert checkout_calls == [(1, action_ref, "b" * 40)]
    assert calls == ["python -m compileall -q ."]
    assert pipeline is not None and pipeline.status is PipelineStatus.FAILED
    assert pipeline.jobs[0].status is PipelineStatus.FAILED
    assert pipeline.jobs[1].status is PipelineStatus.CANCELLED
    # A duplicate delivery sees a final row and cannot run the fixed command.
    assert native_actions.execute_action(queued.id).status is PipelineStatus.FAILED
    with sqlite3.connect(database) as db:
        db.execute(
            """INSERT INTO native_action_runs(id,repository_id,pull_request_id,head_sha,branch,requested_by,reason,action_ref,status,created_at)
               VALUES ('already-running',1,10,?,'feature',1,'','refs/amosclaud/actions/already-running','running','now')""",
            ("e" * 40,),
        )
        db.commit()
    assert native_actions.execute_action("already-running") is None
    assert calls == ["python -m compileall -q ."]
    history = native_actions.action_history(1, 9)
    assert history[0]["head_sha"] == "b" * 40
    assert history[0]["status"] == "failed"


def test_recovery_requeues_only_current_queued_rows_and_fails_legacy_pending(tmp_path, monkeypatch) -> None:
    database = _configure_store(tmp_path, monkeypatch)
    monkeypatch.setattr(native_actions.pipelines, "_get", lambda _action_id: None)
    dispatched = []
    monkeypatch.setattr(native_actions, "dispatch_task", lambda _task, action_id: dispatched.append(action_id))
    native_actions.ensure_schema(sqlite3.connect(database))
    with sqlite3.connect(database) as db:
        db.execute(
            """INSERT INTO native_action_runs(id,repository_id,pull_request_id,head_sha,branch,requested_by,reason,action_ref,status,created_at)
               VALUES ('queued',1,1,?,'feature',1,'', 'refs/amosclaud/actions/queued','queued','now')""",
            ("c" * 40,),
        )
        db.execute(
            """INSERT INTO native_action_runs(id,repository_id,pull_request_id,head_sha,branch,requested_by,reason,action_ref,status,created_at)
               VALUES ('legacy',1,2,?,'feature',1,'',NULL,'pending','now')""",
            ("d" * 40,),
        )
        db.commit()

    assert native_actions.recover_actions() == 1
    assert dispatched == ["queued"]
    with sqlite3.connect(database) as db:
        legacy = db.execute("SELECT status,error_detail FROM native_action_runs WHERE id='legacy'").fetchone()
        queued = db.execute("SELECT status FROM native_action_runs WHERE id='queued'").fetchone()
    assert legacy[0] == "failed"
    assert "queue-time pinned ref" in legacy[1]
    assert queued[0] == "queued"


def test_route_contract_uses_pr_action_history_and_action_specific_merge_gate() -> None:
    source = (Path(__file__).resolve().parents[1] / "amoscloud_ai/api/routes/amosclaud_production.py").read_text()
    assert '"actions": history' in source
    assert "native_actions.queue_action" in source
    assert "native_actions.latest_action(repository_id, pull_request_id)" in source
    assert "Amosclaud Actions must be run from an open pull request" in source


def test_fixed_plan_never_uses_repository_workflow_commands() -> None:
    assert native_actions.ACTION_PLAN == (
        ("compileall", "Compile Python sources", "python -m compileall -q ."),
        ("pytest", "Run pytest", "python -m pytest -q"),
    )
