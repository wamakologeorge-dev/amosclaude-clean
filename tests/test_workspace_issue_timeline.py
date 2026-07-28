"""Regression contracts for the native issue detail and Action timeline."""

from pathlib import Path

from amoscloud_ai.main import create_app

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def _route_paths() -> set[str]:
    return {getattr(route, "path", "") for route in create_app().routes}


def test_native_issue_detail_and_action_routes_are_registered() -> None:
    paths = _route_paths()

    assert "/api/v1/repositories/{repository_id}/issues/{issue_id}" in paths
    assert "/api/v1/repositories/{repository_id}/issues/{issue_id}/actions" in paths


def test_issue_timeline_persists_pipeline_evidence() -> None:
    source = (ROOT / "amoscloud_ai/api/routes/native_issue_timeline.py").read_text(encoding="utf-8")

    assert "native_issue_activity" in source
    assert "pipeline_id" in source
    assert '"source": "native-platform-issue"' in source
    assert "run_agent" in source
    assert "_pipeline_snapshot" in source


def test_workspace_renders_complete_issue_body_and_clickable_detail() -> None:
    source = (WEB / "workspace-issues.js").read_text(encoding="utf-8")

    assert "fullText(issue.body)" in source
    assert 'data-issue-id="${issue.id}"' in source
    assert "openIssue(card.dataset.issueId)" in source
    assert "Complete issue instructions" in source
    assert "Run Amosclaud Action" in source
    assert "/actions" in source


def test_workspace_issue_navigation_cannot_be_overwritten_by_legacy_loader() -> None:
    source = (WEB / "workspace-issues.js").read_text(encoding="utf-8")

    assert "name === 'issues'" in source
    assert "event.stopImmediatePropagation()" in source
    assert "}, true);" in source


def test_workspace_has_separate_issue_and_pull_request_navigation() -> None:
    html = (WEB / "workspace.html").read_text(encoding="utf-8")

    assert 'data-open-tab="issues"' in html
    assert 'data-open-tab="pull-requests"' in html
    assert "/static/workspace-issues.js" in html
    assert "read every instruction" in html


def test_mobile_navigation_shows_all_six_tabs_without_horizontal_wall() -> None:
    css = (WEB / "workspace.css").read_text(encoding="utf-8")

    assert "grid-template-columns:repeat(3,minmax(0,1fr))!important" in css
    assert "overflow:visible!important" in css
    assert ".ws-issue-instructions" in css
    assert "max-height:none!important" in css
