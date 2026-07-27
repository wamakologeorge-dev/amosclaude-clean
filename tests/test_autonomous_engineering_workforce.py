import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

from amoscloud_ai.api.routes.workforce import _observed_at, _safe_data
from amoscloud_ai.engineering_workforce import (
    WorkforcePolicyError,
    asset_health,
    authenticate_asset,
    build_delegation_objective,
    create_asset_token,
    ensure_guardrails,
    ensure_workforce_schema,
    execution_fabric,
    guardrail_dict,
    redact,
    select_execution_target,
    update_guardrails,
)
from amoscloud_ai.main import create_app


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            email TEXT NOT NULL,
            name TEXT,
            is_admin INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO users(id,email,name,is_admin)
        VALUES (1,'owner@example.com','Owner',1);
        CREATE TABLE repositories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            visibility TEXT NOT NULL DEFAULT 'private',
            default_branch TEXT NOT NULL DEFAULT 'main',
            github_full_name TEXT,
            github_html_url TEXT,
            github_default_branch TEXT,
            updated_at TEXT,
            FOREIGN KEY(owner_id) REFERENCES users(id)
        );
        INSERT INTO repositories(
            owner_id,name,github_full_name,github_html_url,github_default_branch,updated_at
        ) VALUES (
            1,'project','example/project','https://github.com/example/project','main',
            '2026-07-27T00:00:00+00:00'
        );
        """
    )
    ensure_workforce_schema(db)
    return db


def test_workforce_routes_are_mounted_on_the_existing_task_control_plane() -> None:
    paths = {getattr(route, "path", "") for route in create_app().routes}
    assert {
        "/api/v1/workforce/overview",
        "/api/v1/workforce/repositories",
        "/api/v1/workforce/execution-fabric",
        "/api/v1/workforce/guardrails",
        "/api/v1/workforce/delegations",
        "/api/v1/workforce/delegations/{delegation_id}/approve",
        "/api/v1/workforce/assets",
        "/api/v1/workforce/assets/{asset_id}/telemetry",
        "/api/v1/workforce/assets/{asset_id}/manifest",
    }.issubset(paths)


def test_guardrails_keep_immutable_safety_controls_enabled() -> None:
    db = _db()
    try:
        initial = guardrail_dict(ensure_guardrails(db, 1))
        assert initial["require_isolated_execution"] is True
        assert initial["require_draft_pull_request"] is True
        assert initial["require_human_merge"] is True
        assert initial["require_rollback_checkpoint"] is True
        assert initial["secret_masking"] is True
        assert initial["allow_force_push"] is False
        assert initial["allow_direct_protected_branch_write"] is False
        assert initial["allow_auto_merge"] is False

        updated = guardrail_dict(
            update_guardrails(
                db,
                1,
                allowed_paths=["src", "tests"],
                protected_paths=[".github/workflows"],
                protected_branches=["main", "production"],
                branch_prefix="amosclaud/workforce",
                max_repair_attempts=3,
            )
        )
        assert updated["allowed_paths"] == ["src", "tests"]
        assert updated["max_repair_attempts"] == 3
        assert updated["allow_force_push"] is False
        assert updated["allow_auto_merge"] is False
    finally:
        db.close()


def test_guardrail_update_rejects_an_empty_write_boundary() -> None:
    db = _db()
    try:
        with pytest.raises(WorkforcePolicyError, match="write path"):
            update_guardrails(
                db,
                1,
                allowed_paths=[],
                protected_paths=[],
                protected_branches=["main"],
                branch_prefix="amosclaud/workforce",
                max_repair_attempts=3,
            )
    finally:
        db.close()


def test_hybrid_scheduler_uses_cloud_without_an_eligible_edge_runner() -> None:
    db = _db()
    try:
        target, runner_id, reason = select_execution_target(
            db,
            1,
            mode="build",
            preference="auto",
        )
        assert target == "github"
        assert runner_id is None
        assert "cloud fallback" in reason
        fabric = execution_fabric(db, 1)
        assert fabric["cloud"]["available"] is True
        assert fabric["edge"]["available"] is False
    finally:
        db.close()


def test_hybrid_scheduler_selects_only_an_explicit_workforce_edge_runner() -> None:
    db = _db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            """INSERT INTO task_runners(
                   id,user_id,name,token_hash,token_prefix,capabilities_json,labels_json,
                   status,version,system_json,created_at,last_seen_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "runner_edge",
                1,
                "Local workstation",
                "hash",
                "prefix",
                json.dumps(["engineering_workforce_v1", "build", "fix"]),
                json.dumps(["local", "gpu"]),
                "online",
                "station/1",
                json.dumps({"cpu": 16}),
                now,
                now,
            ),
        )
        db.commit()

        target, runner_id, reason = select_execution_target(
            db,
            1,
            mode="build",
            preference="auto",
        )
        assert target == "self_hosted"
        assert runner_id == "runner_edge"
        assert "edge runner" in reason

        with pytest.raises(WorkforcePolicyError, match="No online edge runner"):
            select_execution_target(db, 1, mode="test", preference="edge")
    finally:
        db.close()


def test_delegation_objective_encodes_complete_ownership_and_safety_contract() -> None:
    objective = build_delegation_objective(
        delegation_id="work_123",
        kind="epic",
        title="Complete billing migration",
        requirement="Move billing safely and retain backward compatibility.",
        source_reference="https://github.com/example/project/issues/12",
        acceptance_criteria=["All tests pass", "A rollback path is documented"],
        guardrails={
            "max_repair_attempts": 3,
            "allowed_paths": ["src", "tests"],
            "protected_paths": [".github/workflows"],
        },
    )
    assert "Plan -> Execute -> Test -> Diagnose -> Self-correct -> Verify" in objective
    assert "Create an isolated work branch" in objective
    assert "Never force-push and never merge automatically" in objective
    assert "rollback checkpoint" in objective.lower()
    assert "All tests pass" in objective


def test_asset_credentials_are_hashed_and_telemetry_health_is_aggregated() -> None:
    db = _db()
    try:
        token, token_hash, prefix = create_asset_token()
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            """INSERT INTO software_assets(
                   id,user_id,name,repository,asset_type,environment,target_url,
                   telemetry_token_hash,telemetry_token_prefix,created_at,updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "asset_1",
                1,
                "API",
                "example/project",
                "service",
                "production",
                "https://example.com/health",
                token_hash,
                prefix,
                now,
                now,
            ),
        )
        db.execute(
            """INSERT INTO software_asset_telemetry(
                   asset_id,observed_at,online,status_code,latency_ms,cpu_percent,
                   memory_mb,error_count,request_count,active_users,revenue_cents,
                   metadata_json
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "asset_1",
                now,
                1,
                200,
                40.5,
                12.0,
                256.0,
                0,
                120,
                8,
                2599,
                "{}",
            ),
        )
        db.commit()
        asset = authenticate_asset(db, "asset_1", f"Bearer {token}")
        health = asset_health(db, asset)
        assert health["state"] == "operational"
        assert health["window_24h"]["uptime_percent"] == 100.0
        assert health["window_24h"]["average_latency_ms"] == 40.5
        assert health["business"]["revenue_usd"] == 25.99
        assert token not in str(dict(asset))
    finally:
        db.close()


def test_secret_masking_is_recursive_and_timestamp_validation_is_strict() -> None:
    hidden = _safe_data(
        {
            "authorization": "Bearer ghp_abcdefghijklmnopqrstuvwxyz123456",
            "nested": ["api_key=sk-abcdefghijklmnopqrstuvwxyz", {"ok": True}],
        }
    )
    encoded = json.dumps(hidden)
    assert "ghp_" not in encoded
    assert "sk-" not in encoded
    assert "[redacted]" in encoded
    assert "ghp_" not in redact("token=ghp_abcdefghijklmnopqrstuvwxyz123456")
    assert _observed_at("2026-07-27T10:00:00-05:00").endswith("+00:00")
    with pytest.raises(HTTPException, match="ISO-8601"):
        _observed_at("yesterday")


def test_workforce_runner_preserves_branch_isolation_and_human_signoff() -> None:
    source = _source("amoscloud_ai/workforce_task_runner.py")
    worker = _source("amoscloud_ai/worker.py")

    assert '"draft": True' in source
    assert "_assert_base_unchanged" in source
    assert 'repo.git.checkout("-b", branch)' in source
    assert "rollback_checkpoint" in source
    assert "_run_verification" in source
    assert "max_attempts" in source
    assert "force push disabled" in source.lower()
    assert "repo.git.push(\"--set-upstream\"" in source
    assert "--force" not in source
    assert "merge_pull_request" not in source
    assert "_is_workforce_task(task_id)" in worker
    assert "execute_workforce_task(task_id)" in worker


def test_dashboard_exposes_delegation_assets_hybrid_execution_and_guardrails() -> None:
    html = _source("web/workforce.html")
    javascript = _source("web/workforce.js")
    command_center = _source("web/command-center.html")

    assert "Autonomous Engineering Workforce" in html
    assert "Complete requirement" in html
    assert "Authorize bounded repository changes now" in html
    assert "Edge + cloud fabric" in html
    assert "Asset Dashboard" in html
    assert "Revenue telemetry" in html
    assert "/api/v1/workforce/delegations" in javascript
    assert "/api/v1/workforce/overview" in javascript
    assert "/api/v1/workforce/assets" in javascript
    assert "setInterval" in javascript
    assert "/static/workforce.html" in command_center
