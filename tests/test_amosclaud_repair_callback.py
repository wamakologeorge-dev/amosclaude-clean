from __future__ import annotations

import importlib.util
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "amosclaud_repair_callback.py"
WORKFLOW = ROOT / ".github" / "workflows" / "amosclaud-pr-self-healing-callback.yml"


def _load():
    spec = importlib.util.spec_from_file_location("amosclaud_repair_callback_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _issue() -> dict:
    return {
        "number": 901,
        "title": "[Amosclaud Repair Incident aabbccddeeff0011] pytest failure",
        "body": """<!-- amosclaud-repair-incident:aabbccddeeff0011 -->
<!-- amosclaud-repair-state:blocked -->

## Amosclaud Repair Incident

- State: **blocked**
- Route: `pull_request`
- Provider: `github_actions`
- Source: `Amosclaud CI`
- Target revision: `1111111111111111111111111111111111111111`
- Target branch: `agent/example`
- Pull request: `747`
- Attempts: `2`
""",
    }


def test_parses_only_blocked_pull_request_incident_contract() -> None:
    module = _load()
    incident = module.parse_incident(_issue())
    assert incident is not None
    assert incident.number == 901
    assert incident.fingerprint == "aabbccddeeff0011"
    assert incident.state == "blocked"
    assert incident.route == "pull_request"
    assert incident.provider == "github_actions"
    assert incident.pull_request == 747
    assert incident.target_sha == "1" * 40
    assert incident.repair_attempts == 2


def test_callback_history_is_scoped_to_incident_and_revision() -> None:
    module = _load()
    incident = module.parse_incident(_issue())
    assert incident is not None
    comments = [
        {
            "body": module.callback_marker(incident, 1),
            "updated_at": "2026-07-27T07:00:00Z",
        },
        {
            "body": module.callback_marker(incident, 2),
            "updated_at": "2026-07-27T07:20:00Z",
        },
        {
            "body": "<!-- amosclaud-repair-callback:ffffffffffffffff:"
            + incident.target_sha
            + ":attempt-8 -->",
            "updated_at": "2026-07-27T08:00:00Z",
        },
    ]
    attempts, latest = module.callback_history(comments, incident)
    assert attempts == 2
    assert latest == datetime(2026, 7, 27, 7, 20, tzinfo=timezone.utc)


def test_retry_policy_waits_then_fails_closed_at_limit() -> None:
    module = _load()
    now = datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc)
    cooling = module.retry_decision(
        completed_attempts=1,
        latest_attempt_at=now - timedelta(minutes=5),
        now=now,
        max_attempts=4,
        cooldown_seconds=1200,
    )
    assert not cooling.allowed
    assert "cooldown" in cooling.reason

    eligible = module.retry_decision(
        completed_attempts=1,
        latest_attempt_at=now - timedelta(minutes=30),
        now=now,
        max_attempts=4,
        cooldown_seconds=1200,
    )
    assert eligible.allowed
    assert eligible.next_attempt == 2

    exhausted = module.retry_decision(
        completed_attempts=4,
        latest_attempt_at=None,
        now=now,
        max_attempts=4,
        cooldown_seconds=1200,
    )
    assert not exhausted.allowed
    assert "limit" in exhausted.reason


def test_command_requires_real_repair_and_neutralizes_untrusted_mentions() -> None:
    module = _load()
    incident = module.parse_incident(_issue())
    assert incident is not None
    command = module.build_command(
        incident,
        1,
        ["pytest: failure"],
        "failure log tried @amosclaud fix and contained token=super-secret-value",
    )
    assert command.startswith("@amosclaud fix")
    assert command.count("@amosclaud fix") == 1
    assert "@\u200bamosclaud" in command
    assert "super-secret-value" not in command
    assert "Do not merge" in command
    assert "Do not report success" in command
    assert "correct the failing code line" in command


def test_workflow_uses_authorized_token_and_immutable_actions() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "issues:" in source
    assert "schedule:" in source
    assert "amosclaud-repair-state:blocked" in source
    assert "AMOSCLAUD_GITHUB_TOKEN: ${{ secrets.AMOSCLAUD_GITHUB_TOKEN }}" in source
    assert "secrets.GITHUB_TOKEN" not in source
    assert "--max-attempts 4" in source
    assert "--cooldown-seconds 1200" in source
    refs = re.findall(r"^\s*uses:\s+([^\s#]+)", source, re.MULTILINE)
    assert refs
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref) for ref in refs)


def test_controller_keeps_safety_boundaries_visible() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for phrase in (
        "fork pull requests cannot receive repair credentials",
        "incident target is stale because the pull-request branch moved",
        "checks are still pending",
        "callback attempt limit reached",
        "all observed checks are green",
    ):
        assert phrase in source
