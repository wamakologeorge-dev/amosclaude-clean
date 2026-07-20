"""Contract tests for Amosclaud as a standalone development platform."""
from pathlib import Path

from amoscloud_ai.main import create_app


def _route_paths() -> set[str]:
    return {getattr(route, "path", "") for route in create_app().routes}


def test_native_repository_platform_routes_are_registered() -> None:
    paths = _route_paths()
    required = {
        "/api/v1/repositories/{repository_id}/issues",
        "/api/v1/repositories/{repository_id}/issues/{issue_id}",
        "/api/v1/repositories/{repository_id}/pull-requests",
        "/api/v1/repositories/{repository_id}/pull-requests/{pull_request_id}/merge",
        "/api/v1/repositories/{repository_id}/deployment-settings",
    }
    missing = sorted(required - paths)
    assert not missing, f"Missing standalone Amosclaud repository routes: {missing}"


def test_native_platform_does_not_import_github_sdk() -> None:
    source = Path("amoscloud_ai/api/routes/solo_development.py").read_text(encoding="utf-8")
    assert "import github" not in source.lower()
    assert "api.github.com" not in source.lower()
    assert "github_token" not in source.lower()


def test_native_platform_uses_repository_source_for_deployment() -> None:
    source = Path("amoscloud_ai/api/routes/solo_development.py").read_text(encoding="utf-8")
    assert '.amosclaud" / "deployment.json"' in source
    assert "Configure Amosclaud deployment" in source


def test_native_platform_supports_real_issue_pr_and_merge_operations() -> None:
    source = Path("amoscloud_ai/api/routes/solo_development.py").read_text(encoding="utf-8")
    for capability in (
        "native_issues",
        "native_pull_requests",
        "create_issue",
        "create_pull_request",
        "merge_pull_request",
        'repo.git.merge("--no-ff"',
    ):
        assert capability in source
