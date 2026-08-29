"""Worker stations must look like clean CI machines to repository test suites.

A station whose own installation leaks workspace markers (for example
``/app/docker-compose.selfhost.yml``) into the shared filesystem makes user
repositories' legitimate "an unrelated folder is NOT a workspace" tests find a
phantom workspace while walking temp parents to ``/``. The worker scrubs those
markers itself before every Action run, on any deployment method.
"""

from __future__ import annotations

import sqlite3  # noqa: F401  (parity with sibling native-action contracts)
from pathlib import Path

from amoscloud_ai import native_actions, station_hygiene
from amoscloud_ai.api.routes import repositories
from amoscloud_ai.isolated_runner import IsolatedRunResult
from amoscloud_ai.models import PipelineStatus
from amoscloud_ai.station_hygiene import scrub_station_markers, station_hygiene_log_lines


def test_removes_every_present_marker(tmp_path: Path) -> None:
    present = tmp_path / "app" / "docker-compose.selfhost.yml"
    present.parent.mkdir()
    present.write_text("services: {}\n", encoding="utf-8")
    missing = tmp_path / "docker-compose.selfhost.yml"

    removed, stubborn = scrub_station_markers([str(present), str(missing)])

    assert removed == [str(present)]
    assert stubborn == []
    assert not present.exists()


def test_missing_markers_are_quietly_ignored(tmp_path: Path) -> None:
    removed, stubborn = scrub_station_markers([str(tmp_path / "absent.yml")])
    assert removed == [] and stubborn == []


def test_self_host_opt_out_keeps_markers(tmp_path: Path, monkeypatch) -> None:
    marker = tmp_path / "docker-compose.selfhost.yml"
    marker.write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setenv(station_hygiene.KEEP_ENV, "1")

    removed, stubborn = scrub_station_markers([str(marker)])

    assert removed == [] and stubborn == []
    assert marker.exists()


def test_undeletable_marker_is_reported_never_raised(tmp_path: Path, monkeypatch) -> None:
    marker = tmp_path / "docker-compose.selfhost.yml"
    marker.write_text("services: {}\n", encoding="utf-8")

    def refuse(_self):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(Path, "unlink", refuse)

    removed, stubborn = scrub_station_markers([str(marker)])

    assert removed == []
    assert stubborn == [str(marker)]


def test_log_lines_name_each_scrubbed_marker(tmp_path: Path, monkeypatch) -> None:
    marker = tmp_path / "app" / "docker-compose.selfhost.yml"
    marker.parent.mkdir()
    marker.write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr(station_hygiene, "STATION_MARKERS", (str(marker),))

    lines = station_hygiene_log_lines()

    assert len(lines) == 1
    assert "removed the worker station's own workspace marker" in lines[0]
    assert str(marker) in lines[0]
    assert not marker.exists()
    # A clean station has nothing to say.
    assert station_hygiene_log_lines() == []


def test_action_run_scrubs_station_markers_before_the_first_step(
    tmp_path: Path, monkeypatch
) -> None:
    database = tmp_path / "auth.db"
    monkeypatch.setattr(repositories, "DB_PATH", database)
    with repositories._db() as db:
        db.execute("PRAGMA foreign_keys = OFF")
        db.execute(
            "INSERT INTO repositories(id,owner_id,name,created_at,updated_at) VALUES (1,1,'demo','now','now')"
        )
        db.commit()

    marker = tmp_path / "station" / "docker-compose.selfhost.yml"
    marker.parent.mkdir()
    marker.write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr(station_hygiene, "STATION_MARKERS", (str(marker),))

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
        lambda *_args: (None, checkout, None, None),
    )
    monkeypatch.setattr(native_actions, "_remove_checkout", lambda *_args: None)

    seen_at_first_step: list[bool] = []

    def command_runner(_command, **_kwargs):
        seen_at_first_step.append(marker.exists())
        return IsolatedRunResult(returncode=0, output="ok")

    monkeypatch.setattr(native_actions, "run_in_isolated_container", command_runner)

    queued = native_actions.queue_action(
        repository_id=1,
        pull_request_id=11,
        branch="feature/hygiene",
        head_sha="c" * 40,
        requested_by=1,
        reason="test",
    )
    pipeline = native_actions.execute_action(queued.id)

    assert pipeline is not None and pipeline.status is PipelineStatus.SUCCESS
    # The marker was gone before the first fixed command ran.
    assert seen_at_first_step and seen_at_first_step[0] is False
    assert not marker.exists()
    first_step_log = "\n".join(pipeline.jobs[0].logs)
    assert "Station hygiene: removed the worker station's own workspace marker" in first_step_log
    assert str(marker) in first_step_log
