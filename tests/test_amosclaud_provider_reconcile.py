from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"
RECONCILE = SCRIPTS / "amosclaud_provider_reconcile.py"
CLASSIFIER = SCRIPTS / "amosclaud_failure_classifier.py"
WORKFLOW = ROOT / ".github" / "workflows" / "amosclaud-provider-reconcile.yml"


def _load(path: Path, name: str):
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


def _incident(*, number: int = 1107, sha: str = "abc123", source: str = "ci/circleci: chunk-task"):
    return {
        "number": number,
        "body": (
            "<!-- amosclaud-repair-incident:deadbeef -->\n"
            "<!-- amosclaud-repair-state:blocked -->\n\n"
            "## Amosclaud Repair Incident\n\n"
            "- State: **blocked**\n"
            "- Route: `default`\n"
            "- Provider: `circleci`\n"
            f"- Source: `{source}`\n"
            f"- Target revision: `{sha}`\n"
            "- Target branch: `main`\n"
            "- Pull request: `none`\n"
            "- Attempts: `3`\n"
        ),
    }


def test_classifier_marks_non_reproduced_circleci_as_provider_failure() -> None:
    module = _load(CLASSIFIER, "amosclaud_failure_classifier_contract")
    result = module.classify_failure(provider="circleci", source="ci/circleci: chunk-task", reproduced=False)
    assert result == module.FailureClass.CIRCLECI_PROVIDER_FAILURE


def test_success_status_closes_matching_incident_without_source_repair(monkeypatch) -> None:
    module = _load(RECONCILE, "amosclaud_provider_reconcile_status")
    issue = _incident()
    calls = []

    monkeypatch.setattr(module, "_open_circleci_incidents", lambda repository, token: [issue])

    def fake_request(method, url, *, token, payload=None):
        calls.append((method, url, payload))
        return {}

    monkeypatch.setattr(module, "_request_json", fake_request)
    closed = module.reconcile_status_event(
        {"state": "success", "context": "ci/circleci: chunk-task", "sha": "abc123"},
        "owner/repo",
        "token",
    )

    assert closed == 1
    patch = next(payload for method, url, payload in calls if method == "PATCH")
    assert patch["state"] == "closed"
    assert "amosclaud-repair-state:resolved" in patch["body"]
    assert "CIRCLECI_PROVIDER_FAILURE" in patch["body"]
    comment = next(payload for method, url, payload in calls if method == "POST")
    assert "no source repair is required" in comment["body"]


def test_status_does_not_close_wrong_context_or_failed_provider(monkeypatch) -> None:
    module = _load(RECONCILE, "amosclaud_provider_reconcile_ignore")
    monkeypatch.setattr(module, "_open_circleci_incidents", lambda repository, token: [_incident()])
    monkeypatch.setattr(module, "_request_json", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected write")))

    assert module.reconcile_status_event(
        {"state": "failure", "context": "ci/circleci: chunk-task", "sha": "abc123"},
        "owner/repo",
        "token",
    ) == 0
    assert module.reconcile_status_event(
        {"state": "success", "context": "other-provider", "sha": "abc123"},
        "owner/repo",
        "token",
    ) == 0


def test_sweep_reconciles_only_latest_successful_matching_context(monkeypatch) -> None:
    module = _load(RECONCILE, "amosclaud_provider_reconcile_sweep")
    issue = _incident()
    monkeypatch.setattr(module, "_open_circleci_incidents", lambda repository, token: [issue])
    monkeypatch.setattr(
        module,
        "_latest_status_by_context",
        lambda repository, sha, token: {"ci/circleci: chunk-task": "success", "other": "failure"},
    )
    closed = []
    monkeypatch.setattr(
        module,
        "_close_incident",
        lambda repository, issue, *, sha, context, token: closed.append((sha, context)) or True,
    )

    assert module.reconcile_sweep("owner/repo", "token") == 1
    assert closed == [("abc123", "ci/circleci: chunk-task")]


def test_reconciliation_workflow_handles_success_status_and_periodic_sweep() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "status:" in source
    assert "github.event.state == 'success'" in source
    assert "schedule:" in source
    assert "amosclaud_provider_reconcile.py" in source
    assert "issues: write" in source
    assert "statuses: read" in source
