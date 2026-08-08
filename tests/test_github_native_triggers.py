from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

from amoscloud_ai.api.routes import auth, github_native_triggers


@pytest.fixture
def native_trigger_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    database = tmp_path / "native-trigger.db"
    monkeypatch.setattr(auth, "DB_PATH", database)
    monkeypatch.setenv("AMOSCLAUD_GITHUB_PIPELINE_TOKEN", "native-trigger-secret")
    with auth._connect() as db:
        cursor = db.execute(
            """INSERT INTO users(name,email,password_hash,provider,is_admin,created_at)
               VALUES (?,?,NULL,'github-native',1,?)""",
            ("Automation Owner", "automation@example.com", datetime.now(timezone.utc).isoformat()),
        )
        user_id = int(cursor.lastrowid)
        db.commit()
    monkeypatch.setenv("AMOSCLAUD_GITHUB_AUTOMATION_USER_ID", str(user_id))
    return user_id


def _event(**overrides):
    values = {
        "delivery_id": "github-run-12345678",
        "event": "push",
        "action": "",
        "repository": "wamakologeorge-dev/amosclaude-clean",
        "ref": "refs/heads/main",
        "sha": "a" * 40,
        "actor": "wamakologeorge-dev",
        "changed_files": [
            ".github/workflows/ci.yml",
            "legacy/application.py",
            "amoscloud_ai/main.py",
        ],
        "repository_scope": {
            "scope": "all-changed-files",
            "file_count": 3,
            "excluded_paths": [],
            "includes_legacy_applications": True,
            "includes_github_native_applications": True,
        },
    }
    values.update(overrides)
    return github_native_triggers.GitHubNativeEvent(**values)


def test_push_creates_one_shared_build_pipeline(native_trigger_db: int) -> None:
    result = github_native_triggers.receive_github_event(
        _event(),
        authorization=None,
        x_amosclaud_github_token="native-trigger-secret",
    )

    assert result["deduplicated"] is False
    pipeline = result["pipeline"]
    assert pipeline["mode"] == "build"
    assert pipeline["branch"] == "main"
    assert pipeline["allow_writes"] is False
    assert pipeline["project_id"] == "github:wamakologeorge-dev/amosclaude-clean"
    assert pipeline["metadata"]["source"] == "github-native"
    assert pipeline["metadata"]["repository_scope"]["excluded_paths"] == []
    assert pipeline["metadata"]["repository_scope"]["includes_legacy_applications"] is True
    assert pipeline["metadata"]["repository_scope"]["includes_github_native_applications"] is True


def test_delivery_is_deduplicated(native_trigger_db: int) -> None:
    first = github_native_triggers.receive_github_event(
        _event(),
        authorization="Bearer native-trigger-secret",
        x_amosclaud_github_token=None,
    )
    second = github_native_triggers.receive_github_event(
        _event(),
        authorization="Bearer native-trigger-secret",
        x_amosclaud_github_token=None,
    )

    assert second["deduplicated"] is True
    assert second["pipeline"]["id"] == first["pipeline"]["id"]


def test_schedule_maps_to_monitor_and_fix_stays_approval_gated(native_trigger_db: int) -> None:
    scheduled = github_native_triggers.receive_github_event(
        _event(
            delivery_id="github-run-87654321",
            event="schedule",
            changed_files=[],
            repository_scope={
                "scope": "all-tracked-files",
                "file_count": 500,
                "excluded_paths": [],
                "includes_legacy_applications": True,
                "includes_github_native_applications": True,
            },
        ),
        authorization=None,
        x_amosclaud_github_token="native-trigger-secret",
    )
    requested_fix = github_native_triggers.receive_github_event(
        _event(
            delivery_id="github-run-11223344",
            event="workflow_dispatch",
            requested_mode="fix",
        ),
        authorization=None,
        x_amosclaud_github_token="native-trigger-secret",
    )

    assert scheduled["pipeline"]["mode"] == "monitor"
    assert requested_fix["pipeline"]["mode"] == "fix"
    assert requested_fix["pipeline"]["allow_writes"] is False
    assert requested_fix["pipeline"]["approvals"][0]["state"] == "pending"


def test_invalid_token_is_rejected(native_trigger_db: int) -> None:
    with pytest.raises(HTTPException) as error:
        github_native_triggers.receive_github_event(
            _event(),
            authorization="Bearer wrong-token",
            x_amosclaud_github_token=None,
        )
    assert error.value.status_code == 401


def test_trigger_script_classifies_native_legacy_and_unclassified_files() -> None:
    path = Path("scripts/ci/amosclaud_github_native_trigger.py")
    spec = importlib.util.spec_from_file_location("amosclaud_native_trigger", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module._surface(".github/workflows/native.yml") == "github-native-applications"
    assert module._surface("legacy/old_app.py") == "legacy-applications"
    assert module._surface("unknown-system/file.cb") == "repository-root-or-unclassified-legacy"
    scope = module._scope(
        [".github/workflows/native.yml", "legacy/old_app.py"],
        [".github/workflows/native.yml", "legacy/old_app.py", "root.txt"],
        "schedule",
    )
    assert scope["scope"] == "all-tracked-files"
    assert scope["file_count"] == 3
    assert scope["excluded_paths"] == []
