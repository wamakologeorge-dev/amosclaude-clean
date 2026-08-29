"""The fixed Action plan must be runnable on every Amosclaud worker station.

The authoritative native Action plan runs ``python -m pytest -q`` inside the
isolated runner. Real repositories declare pytest plugins in their test
configuration (``pytest.ini`` with ``asyncio_mode``, conftest modules that
import ``pytest_asyncio``). When the production image ships bare pytest
without the canonical plugin toolkit, pytest exits with usage-error code 4
before collecting a single test and every native Action on such a repository
fails for an environmental reason the user cannot see. These contracts pin
the worker toolkit and the plain-language interpretation of that outcome.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from amoscloud_ai import native_actions
from amoscloud_ai.api.routes import repositories
from amoscloud_ai.isolated_runner import IsolatedRunResult
from amoscloud_ai.models import PipelineStatus

REPO_ROOT = Path(__file__).resolve().parents[1]


def _configure_store(tmp_path: Path, monkeypatch) -> Path:
    database = tmp_path / "auth.db"
    monkeypatch.setattr(repositories, "DB_PATH", database)
    with repositories._db() as db:
        db.execute("PRAGMA foreign_keys = OFF")
        db.execute(
            "INSERT INTO repositories(id,owner_id,name,created_at,updated_at)"
            " VALUES (1,1,'demo','now','now')"
        )
        db.commit()
    return database


def test_production_image_installs_the_fixed_plan_test_toolkit() -> None:
    """The image that runs native Actions ships the canonical pytest toolkit.

    ``requirements.txt`` is the canonical manifest and already pins
    pytest-asyncio and pytest-cov. The production Dockerfile intentionally
    installs its packages inline, so it must carry the same test toolkit or
    fixed-plan pytest runs collapse with exit code 4 on any repository whose
    conftest imports a pytest plugin.
    """

    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    for required in ("pytest>=", "pytest-asyncio>=", "pytest-cov>="):
        assert required in dockerfile, (
            f"production Dockerfile no longer installs {required!r}; the fixed "
            "native Action plan cannot run repository test suites without it"
        )


def test_pytest_usage_error_is_explained_in_plain_language(tmp_path, monkeypatch) -> None:
    """Exit code 4 from the pytest step is stored with a human explanation."""

    database = _configure_store(tmp_path, monkeypatch)
    stored = {}
    checkout = tmp_path / "detached"
    checkout.mkdir()
    monkeypatch.setattr(native_actions, "_pin_action_ref", lambda *_args: None)
    monkeypatch.setattr(
        native_actions.pipelines,
        "_save",
        lambda pipeline, *_args: stored.update({pipeline.id: pipeline.model_copy(deep=True)}),
    )
    monkeypatch.setattr(native_actions.pipelines, "_get", lambda action_id: stored.get(action_id))
    monkeypatch.setattr(native_actions, "dispatch_task", lambda *_args: None)
    monkeypatch.setattr(
        native_actions,
        "_detached_checkout",
        lambda _repository_id, _action_ref, _sha: (None, checkout, None, None),
    )
    monkeypatch.setattr(native_actions, "_remove_checkout", lambda *_args: None)

    def runner(command, **_kwargs):
        if "compileall" in command:
            return IsolatedRunResult(returncode=0, output="compiled")
        return IsolatedRunResult(
            returncode=4,
            output="ImportError while loading conftest: No module named 'pytest_asyncio'",
        )

    monkeypatch.setattr(native_actions, "run_in_isolated_container", runner)

    queued = native_actions.queue_action(
        repository_id=1,
        pull_request_id=11,
        branch="feature/toolkit",
        head_sha="c" * 40,
        requested_by=1,
        reason="test",
    )
    pipeline = native_actions.execute_action(queued.id)

    assert pipeline is not None and pipeline.status is PipelineStatus.FAILED
    assert pipeline.jobs[0].status is PipelineStatus.SUCCESS
    assert pipeline.jobs[1].status is PipelineStatus.FAILED
    with sqlite3.connect(database) as db:
        detail = db.execute(
            "SELECT error_detail FROM native_action_runs WHERE id=?", (queued.id,)
        ).fetchone()[0]
    assert "Run pytest returned 4" in detail
    assert "could not start" in detail
    assert "execution log" in detail.lower()


def test_plain_test_failures_keep_their_meaning_and_timeouts_stay_unembellished() -> None:
    """Exit 1 explains failing tests; a timeout is never re-interpreted."""

    pytest_job = native_actions.PipelineJob(
        id="pytest", name="Run pytest", status=PipelineStatus.RUNNING, logs=[]
    )
    compile_job = native_actions.PipelineJob(
        id="compileall", name="Compile Python sources", status=PipelineStatus.RUNNING, logs=[]
    )

    failed = native_actions._failure_detail(
        pytest_job, IsolatedRunResult(returncode=1, output="")
    )
    assert failed.startswith("Run pytest returned 1")
    assert "at least one test failed" in failed

    timed_out = native_actions._failure_detail(
        pytest_job, IsolatedRunResult(returncode=4, output="", timed_out=True)
    )
    assert timed_out == "Run pytest returned 4 (timed out)"

    compile_failure = native_actions._failure_detail(
        compile_job, IsolatedRunResult(returncode=4, output="")
    )
    assert compile_failure == "Compile Python sources returned 4"
