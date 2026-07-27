"""Contracts for the live workspace terminal and GitHub pull-request feed."""

from pathlib import Path

from amoscloud_ai.api.routes.github_pull_requests import github_pull_request_dict
from amoscloud_ai.main import create_app


def test_live_github_pull_request_route_is_registered() -> None:
    paths = {getattr(route, "path", "") for route in create_app().routes}
    assert "/api/v1/github/repositories/{repository_id}/pull-requests" in paths


def test_github_pull_request_normalizer_marks_merged_items() -> None:
    item = {
        "number": 758,
        "title": "Add repository mapper",
        "body": "Verified change",
        "state": "closed",
        "draft": False,
        "html_url": "https://github.com/example/project/pull/758",
        "merge_commit_sha": "a" * 40,
        "merged_at": "2026-07-27T10:07:32Z",
        "updated_at": "2026-07-27T10:07:34Z",
        "head": {"ref": "feature/mapper"},
        "base": {"ref": "main"},
        "user": {"login": "developer"},
    }

    result = github_pull_request_dict(item)

    assert result["id"] == 758
    assert result["state"] == "merged"
    assert result["source"] == "github"
    assert result["head_branch"] == "feature/mapper"
    assert result["base_branch"] == "main"
    assert result["merged_at"] == "2026-07-27T10:07:32Z"


def test_github_pull_request_normalizer_keeps_unmerged_closed_state() -> None:
    result = github_pull_request_dict(
        {
            "number": 12,
            "title": "Closed without merge",
            "state": "closed",
            "html_url": "https://github.com/example/project/pull/12",
            "head": {"ref": "old-branch"},
            "base": {"ref": "main"},
        }
    )

    assert result["state"] == "closed"
    assert result["merged_at"] is None


def test_workspace_prefers_live_github_pull_requests() -> None:
    source = Path("web/workspace-tools.js").read_text(encoding="utf-8")
    assert "/api/v1/github/repositories/${repositoryId}/pull-requests" in source
    assert "open, closed, and merged" in source
    assert "source === 'amosclaud' && pr.state === 'open'" in source


def test_terminal_auto_connects_and_describes_developer_tools() -> None:
    source = Path("web/cloud-workspace.js").read_text(encoding="utf-8")
    assert "if (started) await connect();" in source
    assert "if (running) await connect();" in source
    assert "Developer toolchain:" in source
    assert "separate Docker workspace runtime" in source


def test_workspace_image_contains_practical_developer_toolchain() -> None:
    dockerfile = Path(
        "services/workspace_runtime/workspace-image/Dockerfile"
    ).read_text(encoding="utf-8")
    for package in (
        "build-essential",
        "cmake",
        "fd-find",
        "git-lfs",
        "nodejs",
        "python3-dev",
        "python3-venv",
        "ripgrep",
        "shellcheck",
        "sqlite3",
    ):
        assert package in dockerfile
    assert "USER developer" in dockerfile
