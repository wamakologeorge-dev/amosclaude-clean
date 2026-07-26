from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "amosclaud_incident_deduplicator.py"
WORKFLOW = ROOT / ".github" / "workflows" / "amosclaud-incident-deduplicator.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "amosclaud_incident_deduplicator_contract", SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _incident(
    number: int,
    *,
    source: str = "Build and Verify",
    revision: str = "a" * 40,
    state: str = "open",
    marker: str = "",
):
    return {
        "number": number,
        "title": f"[Amosclaud Repair Incident abc{number}] {source}",
        "body": (
            f"{marker}\n"
            "- State: **blocked**\n"
            "- Route: `default`\n"
            "- Provider: `github_actions`\n"
            f"- Source: `{source}`\n"
            f"- Target revision: `{revision}`\n"
            "- Target branch: `main`\n"
            "- Pull request: `none`\n"
        ),
        "state": state,
        "created_at": f"2026-07-{number:02d}T00:00:00Z",
        "user": {"login": "github-actions[bot]"},
    }


def test_same_workflow_and_branch_share_key_across_commits() -> None:
    module = _load()
    first = _incident(1, revision="a" * 40)
    second = _incident(2, revision="b" * 40)

    assert module.canonical_key(first) == module.canonical_key(second)


def test_different_workflows_do_not_get_merged() -> None:
    module = _load()
    first = _incident(1, source="Build and Verify")
    second = _incident(2, source="Python package")

    assert module.canonical_key(first) != module.canonical_key(second)


def test_legacy_fixer_titles_are_stable_across_revisions() -> None:
    module = _load()
    first = {
        "number": 688,
        "title": "Amosclaud Fixer could not repair github-actions:🚀 Amosclaud AI - CI Pipeline",
        "body": "The autonomous fixer could not produce a verified repair for commit `a" + "1" * 39 + "`.",
        "state": "open",
        "created_at": "2026-07-26T08:31:04Z",
        "user": {"login": "github-actions[bot]"},
    }
    second = dict(first)
    second["number"] = 700
    second["body"] = "The autonomous fixer could not produce a verified repair for commit `b" + "2" * 39 + "`."

    assert module.canonical_key(first) == module.canonical_key(second)


def test_unrelated_human_issue_is_not_touched() -> None:
    module = _load()
    issue = {
        "number": 10,
        "title": "Feature request",
        "body": "Please add a feature.",
        "state": "open",
        "user": {"login": "repository-owner"},
    }

    assert module.canonical_key(issue) is None


def test_existing_marker_wins_even_when_canonical_is_closed() -> None:
    module = _load()
    key = module.canonical_key(_incident(1))
    marker = module.marker_for_key(key)
    closed_canonical = _incident(1, state="closed", marker=marker)
    new_duplicate = _incident(2)

    chosen = module._choose_canonical([closed_canonical, new_duplicate], marker)

    assert chosen["number"] == 1


def test_workflow_is_bounded_and_does_not_create_issues() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "types: [opened, reopened, edited]" in source
    assert "issues: write" in source
    assert "contents: read" in source
    assert "cancel-in-progress: false" in source
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in source
    assert "gh issue create" not in source
    assert "amosclaud_incident_deduplicator.py" in source
