from __future__ import annotations

from pathlib import Path

from scripts.ci import sync_github_labels

ROOT = Path(__file__).resolve().parents[1]


def test_label_manifest_has_complete_unique_taxonomy() -> None:
    labels = sync_github_labels.load_manifest(ROOT / ".github" / "labels.yml")
    names = {label["name"] for label in labels}

    assert len(names) == len(labels)
    assert {
        "area:pipeline",
        "area:runtime",
        "area:java-pod",
        "area:legacy",
        "type:bug",
        "type:feature",
        "size:s",
        "size:m",
        "priority:p0",
        "priority:p2",
        "status:needs-triage",
        "status:ready-to-merge",
        "status:waiting-for-approval",
    } <= names


def test_label_sync_is_manual_additive_and_does_not_request_contents_write() -> None:
    workflow = (ROOT / ".github" / "workflows" / "sync-labels.yml").read_text(
        encoding="utf-8"
    )
    script = (ROOT / "scripts" / "ci" / "sync_github_labels.py").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in workflow
    assert "issues: write" in workflow
    assert "contents: read" in workflow
    assert "contents: write" not in workflow
    assert 'request_json("DELETE"' not in script
    assert 'result: dict[str, list[str]] = {"created": [], "updated": [], "unchanged": []}' in script


def test_issue_and_pull_request_templates_use_canonical_labels() -> None:
    bug_form = (ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").read_text(
        encoding="utf-8"
    )
    feature_form = (
        ROOT / ".github" / "ISSUE_TEMPLATE" / "feature_request.yml"
    ).read_text(encoding="utf-8")
    pull_request = (ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text(
        encoding="utf-8"
    )

    assert 'labels: ["type:bug", "status:needs-triage"]' in bug_form
    assert 'labels: ["type:feature", "status:needs-triage"]' in feature_form
    assert "Suggested labels" in pull_request
    assert "area:pipeline" in pull_request
