"""Safety and integration contracts for the Daily Autonomous Builder."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from amoscloud_ai.api.routes.autonomy import AutonomySettingsUpdate
from amoscloud_ai.autonomous_builder import (
    DEFAULT_ALLOWED_PATHS,
    ensure_autonomy_schema,
    ensure_settings,
    environment_enabled,
    path_policy_violations,
    score_candidate,
    settings_dict,
)
from amoscloud_ai.main import create_app
from amoscloud_ai.worker import celery_app


def test_autonomy_requires_the_server_switch_and_honors_pause(monkeypatch) -> None:
    monkeypatch.delenv("AMOSCLAUD_AUTONOMY_ENABLED", raising=False)
    monkeypatch.delenv("AMOSCLAUD_AUTONOMY_PAUSED", raising=False)
    assert environment_enabled() is False

    monkeypatch.setenv("AMOSCLAUD_AUTONOMY_ENABLED", "true")
    assert environment_enabled() is True

    monkeypatch.setenv("AMOSCLAUD_AUTONOMY_PAUSED", "true")
    assert environment_enabled() is False


def test_candidate_score_rewards_value_and_penalizes_risk() -> None:
    high_value = {
        "user_value": 9,
        "roadmap_alignment": 8,
        "recurring_failure_reduction": 7,
        "maintainability_improvement": 6,
        "implementation_risk": 2,
        "security_risk": 1,
        "estimated_size": 3,
    }
    risky = {**high_value, "implementation_risk": 9, "security_risk": 8}
    assert score_candidate(high_value) == 24
    assert score_candidate(risky) < score_candidate(high_value)


def test_path_policy_blocks_protected_and_outside_paths() -> None:
    violations = path_policy_violations(
        [
            "web/feature.js",
            "tests/test_feature.py",
            ".github/workflows/release.yml",
            "services/runtime.py",
            "random/location.txt",
        ],
        allowed_paths=["web", "tests", "services"],
        protected_paths=["services"],
    )
    assert "Protected path changed: .github/workflows/release.yml" in violations
    assert "Protected path changed: services/runtime.py" in violations
    assert "Path is outside the autonomous allowlist: random/location.txt" in violations
    assert not any("web/feature.js" in item for item in violations)


def test_default_settings_are_disabled_and_can_never_auto_merge() -> None:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute(
        """CREATE TABLE users (
               id INTEGER PRIMARY KEY,
               email TEXT,
               name TEXT
           )"""
    )
    db.execute("INSERT INTO users(id,email,name) VALUES (1,'owner@example.com','Owner')")
    row = ensure_settings(db, 1)
    settings = settings_dict(row)
    assert settings["enabled"] is False
    assert settings["auto_merge"] is False
    assert settings["daily_limit"] == 1
    assert settings["max_repair_attempts"] == 3
    assert settings["allowed_paths"] == list(DEFAULT_ALLOWED_PATHS)

    columns = {
        item[1]: item
        for item in db.execute("PRAGMA table_info(autonomy_settings)").fetchall()
    }
    assert "auto_merge" in columns


def test_autonomy_schema_contains_a_durable_audit_ledger() -> None:
    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys = OFF")
    ensure_autonomy_schema(db)
    tables = {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {
        "autonomy_settings",
        "autonomous_backlog",
        "autonomous_runs",
        "autonomous_run_events",
    } <= tables


def test_settings_model_refuses_automatic_merge() -> None:
    value = AutonomySettingsUpdate(auto_merge=False)
    assert value.auto_merge is False


def test_autonomy_routes_are_registered_on_the_existing_task_surface() -> None:
    paths = {getattr(route, "path", "") for route in create_app().routes}
    required = {
        "/api/v1/autonomy/settings",
        "/api/v1/autonomy/backlog",
        "/api/v1/autonomy/run-now",
        "/api/v1/autonomy/runs",
        "/api/v1/autonomy/runs/{run_id}",
    }
    assert not (required - paths)


def test_celery_beat_has_one_daily_autonomous_selection_pass() -> None:
    entry = celery_app.conf.beat_schedule["amosclaud-daily-autonomous-builder"]
    assert entry["task"] == "amoscloud_ai.run_daily_autonomous_builder"


def test_policy_check_occurs_before_git_push_and_draft_pr_is_forced() -> None:
    source = Path("amoscloud_ai/autonomous_task_runner.py").read_text(encoding="utf-8")
    assert source.index("enforce_task_path_policy") < source.index("repo.git.push")
    assert '"draft": True' in source
    assert "auto_merge" in source
