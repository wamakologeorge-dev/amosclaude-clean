from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "amosclaud-repair-control-plane.yml"
CONTROL = ROOT / ".github" / "scripts" / "amosclaud_repair_control.py"
EVIDENCE = ROOT / ".github" / "scripts" / "amosclaud_repair_evidence.py"
VERIFY = ROOT / ".github" / "scripts" / "amosclaud_repair_verify.py"
POLICY = ROOT / ".amosclaud" / "repair-control-plane.json"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_control_plane_watches_the_exact_live_server_name_and_repair_engines() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "🚀 Amosclaud AI — Live Server Check" in source
    assert "🚀 Amoscloud AI — Live Server Check" not in source
    assert "Amosclaud Autonomous Fixer" in source
    assert "Amosclaud Pull Request CI Repair" in source
    assert "Amosclaud Repair Control Plane" in source


def test_incident_fingerprint_is_stable_and_repair_markers_are_reused() -> None:
    module = _load(CONTROL, "amosclaud_repair_control_contract")
    first = module._fingerprint("owner/repo", "abc", "pull_request")
    second = module._fingerprint("owner/repo", "abc", "pull_request")
    assert first == second
    assert len(first) == 20
    assert module.REPAIR_MARKER_RE.search(f"fix: repair [incident:{first}]").group(1) == first


def test_verification_environment_removes_all_repair_credentials(monkeypatch) -> None:
    module = _load(VERIFY, "amosclaud_repair_verify_contract")
    monkeypatch.setenv("AMOSCLAUD_API_KEY", "secret")
    monkeypatch.setenv("AMOSCLAUD_AUTONOMOUS_TOKEN", "secret")
    monkeypatch.setenv("CIRCLECI_TOKEN", "secret")
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setenv("NORMAL_SETTING", "safe")
    clean = module.sanitized_environment()
    assert clean["NORMAL_SETTING"] == "safe"
    assert "AMOSCLAUD_API_KEY" not in clean
    assert "AMOSCLAUD_AUTONOMOUS_TOKEN" not in clean
    assert "CIRCLECI_TOKEN" not in clean
    assert "GITHUB_TOKEN" not in clean


def test_circleci_collector_supports_logs_and_failed_workflow_reruns() -> None:
    source = EVIDENCE.read_text(encoding="utf-8")
    assert "api/v1.1/project/github" in source
    assert "output_url" in source
    assert "api/v2/workflow/{workflow_id}/rerun" in source
    assert '"from_failed": True' in source


def test_policy_has_all_routes_adapters_and_safety_guards() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert policy["routes"]["default_branch"] == "review_branch"
    assert policy["routes"]["same_repository_pull_request"] == "original_pull_request_branch"
    assert policy["routes"]["protected_repair_engine"] == "maintenance_pull_request"
    assert policy["credentials"]["verification_must_be_credential_free"] is True
    assert set(policy["verification"]["adapters"]) == {
        "javascript",
        "github_pages",
        "workflow",
        "api_or_live_server",
        "docker",
    }
    assert policy["maintenance_patch"]["human_approval_required"] is True
    assert policy["publishing"]["direct_default_branch_writes"] is False
    assert policy["publishing"]["force_push"] is False


def test_successful_repair_checks_reconcile_and_close_incidents() -> None:
    source = CONTROL.read_text(encoding="utf-8")
    assert "def reconcile(" in source
    assert "check-runs?per_page=100" in source
    assert '"state": "closed"' in source
    assert "All observed checks completed successfully" in source


def test_scheduled_scan_does_not_call_the_model_when_healthy() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    health = source.index("Close healthy scheduled scan without model use")
    candidate = source.index("Generate bounded repair candidate")
    assert health < candidate
    assert "steps.reproduce.outputs.reproduced == 'true'" in source
