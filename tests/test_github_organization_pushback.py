import json
from pathlib import Path

import pytest
import yaml
from fastapi import HTTPException
from urllib.parse import urlparse

import yaml
from git import Repo

from amoscloud_ai.api.routes import github_app, github_repositories, platform_services
from amoscloud_ai.api.routes.github_organization_publish import (
    GitHubOrganizationPublishRequest,
    _canonical_origin,
    _creation_path,
    _github_remote_full_name,
    _selected_local_branch,
    _validated_owner,
)
from amoscloud_ai.api.routes.real_repositories import RealRepositoryCreate
from amoscloud_ai.cloud_configuration import load_cloud_configuration
from amoscloud_ai.github_repository_sync import _synchronization_remote
from amoscloud_ai.main import app
from amoscloud_ai.route_discovery import route_paths


ROOT = Path(__file__).resolve().parents[1]


def test_organization_publish_routes_are_mounted() -> None:
    github_paths = route_paths(github_repositories.router.routes)
    assert "/github/connect-organizations" in github_paths
    assert "/github/organizations" in github_paths
    assert "/github/repositories/{repository_id}/publish" in github_paths
    assert "/github/repositories/{repository_id}/sync-status" in github_paths

    platform_paths = route_paths(platform_services.router.routes)
    assert "/platform/cloud-configuration" in platform_paths

    application_paths = route_paths(app.routes)
    assert "/api/v1/github/connect-organizations" in application_paths
    assert "/api/v1/github/organizations" in application_paths
    assert "/api/v1/github/repositories/{repository_id}/publish" in application_paths
    assert "/api/v1/github/repositories/{repository_id}/sync-status" in application_paths
    assert "/api/v1/platform/cloud-configuration" in application_paths


def test_personal_and_organization_creation_paths_are_distinct() -> None:
    assert _creation_path("George", "george") == "/user/repos"
    assert _creation_path("Amosclaud1", "george") == "/orgs/Amosclaud1/repos"
    assert _validated_owner("Amosclaud1") == "Amosclaud1"

    create = RealRepositoryCreate(name="project", owner="Amosclaud1")
    publish = GitHubOrganizationPublishRequest(owner="Amosclaud1")
    assert create.owner == publish.owner == "Amosclaud1"


def test_reconnect_flow_requests_org_and_workflow_access() -> None:
    source = (ROOT / "amoscloud_ai/api/routes/github_organization_publish.py").read_text(
        encoding="utf-8"
    )
    assert '"scope": "read:user user:email repo workflow read:org"' in source
    assert "Organization policy, SSO, or app approval may still be required" in source


def test_webhook_signature_uses_full_sha256_header(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_APP_WEBHOOK_SECRET", "It's a Secret to Everybody")
    github_app._verify_signature(
        b"Hello, World!",
        "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17",
    )


def test_production_webhook_fails_closed_with_environment_variable(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_APP_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("AMOSCLAUD_ENV", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(HTTPException) as error:
        github_app._verify_signature(b"{}", None)
    assert error.value.status_code == 503


def test_push_webhook_enforces_policy_and_passes_immutable_id() -> None:
    source = (ROOT / "amoscloud_ai/api/routes/github_app.py").read_text(
        encoding="utf-8"
    )
    assert "_github_to_platform_policy()" in source
    assert "background_tasks.add_task" in source
    assert "synchronize_github_push" in source
    assert "repository_id," in source
    assert 'event == "push"' in source
    assert '"repository"' in source
    assert "_refresh_repository_mapping(payload, event, action)" in source
def test_push_webhook_queues_fast_forward_sync() -> None:
    source = (ROOT / "amoscloud_ai/api/routes/github_app.py").read_text(
        encoding="utf-8"
    )
    assert "background_tasks.add_task" in source
    assert "synchronize_github_push" in source
    assert 'event == "push"' in source

    sync_source = (ROOT / "amoscloud_ai/github_repository_sync.py").read_text(
        encoding="utf-8"
    )
    assert "repo.is_dirty(untracked_files=True)" in sync_source
    assert "_detached_head_is_referenced(repo)" in sync_source
    assert "repo.is_ancestor(local_ref, remote_ref)" in sync_source
    assert "automatic pull was blocked" in sync_source
    assert "repo.head.reset(remote_ref, index=True, working_tree=True)" in sync_source
    assert "github_last_sync_attempt_at" in sync_source
    assert "COLLATE NOCASE" in sync_source
    assert "repo.is_ancestor(local_ref, remote_ref)" in sync_source
    assert "automatic pull was blocked" in sync_source
    assert "repo.head.reset(remote_ref, index=True, working_tree=True)" in sync_source


def test_publish_keeps_github_as_canonical_origin(tmp_path: Path) -> None:
    repo = Repo.init(tmp_path / "project")
    origin = _canonical_origin(repo, "example/project")
    assert origin.name == "origin"
    assert origin.url == "https://github.com/example/project.git"


def test_publish_refuses_non_github_and_mismatched_origins(tmp_path: Path) -> None:
    assert _github_remote_full_name("git@github.com:Example/Project.git") == "Example/Project"
    assert _github_remote_full_name("https://github.com/Example/Project.git") == "Example/Project"
    with pytest.raises(HTTPException, match="not hosted on GitHub"):
        _github_remote_full_name("https://gitlab.com/example/project.git")

    repo = Repo.init(tmp_path / "mismatch")
    repo.create_remote("origin", "https://github.com/other/project.git")
    with pytest.raises(HTTPException, match="local origin points"):
        _canonical_origin(repo, "example/project")


def test_publish_uses_the_requested_existing_local_branch(tmp_path: Path) -> None:
    repo = Repo.init(tmp_path / "branches", initial_branch="main")
    (tmp_path / "branches" / "README.md").write_text("main\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("main")
    repo.create_head("release")

    assert _selected_local_branch(repo, "release", "main") == "release"
    with pytest.raises(HTTPException, match="does not exist"):
        _selected_local_branch(repo, "missing", "main")


def test_publisher_holds_lock_preserves_visibility_and_pushes_named_ref() -> None:
    source = (ROOT / "amoscloud_ai/api/routes/github_organization_publish.py").read_text(
        encoding="utf-8"
    )
    assert "with _repo_lock(repository_id):" in source
    assert "existing_visibility != body.visibility" in source
    assert 'refspec = f"refs/heads/{branch}:refs/heads/{branch}"' in source
    assert "github_repository_id" in source
    assert "github_default_branch" in source
    assert "_rollback_created_repository" in source


def test_sync_supports_imported_and_legacy_published_remotes(tmp_path: Path) -> None:
    origin_repo = Repo.init(tmp_path / "origin")
    origin_repo.create_remote("origin", "https://github.com/example/origin.git")
    assert _synchronization_remote(origin_repo).name == "origin"

    published_repo = Repo.init(tmp_path / "published")
    published_repo.create_remote(
        "amosclaud-publish",
        "https://github.com/example/published.git",
    )
    assert _synchronization_remote(published_repo).name == "amosclaud-publish"


def test_cloud_policy_is_server_managed_and_read_only() -> None:
    load_cloud_configuration.cache_clear()
    configuration = load_cloud_configuration()
    status = configuration.public_status()

    assert status["server_managed"] is True
    allowlist = status["network_domain_allowlist"]
    assert isinstance(allowlist, (list, tuple, set))
    assert any(domain == "api.github.com" for domain in allowlist)

    def _normalized_host(entry: str) -> str | None:
        parsed = urlparse(entry)
        host = parsed.hostname
        if host is None:
            host = urlparse(f"//{entry}").hostname
        return host.rstrip(".").lower() if host else None

    allowlist_hosts = {
        host
        for entry in status["network_domain_allowlist"]
        for host in [_normalized_host(entry)]
        if host is not None
    }
    assert "api.github.com" in allowlist_hosts
    assert status["repository_sync"]["direction"] == "bidirectional"
    assert status["repository_sync"]["overwrite_dirty_workspaces"] is False
    assert status["repository_sync"]["overwrite_diverged_history"] is False
    assert status["default_sandbox_image"]

    route_source = (ROOT / "amoscloud_ai/api/routes/cloud_configuration.py").read_text(
        encoding="utf-8"
    )
    assert '@router.get("/cloud-configuration")' in route_source
    assert "@router.post" not in route_source
    assert "@router.put" not in route_source
    assert "@router.patch" not in route_source


def test_devcontainer_runs_app_postgres_redis_and_docker() -> None:
    devcontainer = json.loads(
        (ROOT / ".devcontainer/devcontainer.json").read_text(encoding="utf-8")
    )
    compose = yaml.safe_load(
        (ROOT / ".devcontainer/docker-compose.yml").read_text(encoding="utf-8")
    )
    dockerfile = (ROOT / ".devcontainer/Dockerfile").read_text(encoding="utf-8")

    assert devcontainer["dockerComposeFile"] == "docker-compose.yml"
    assert devcontainer["service"] == "app"
    assert devcontainer["privileged"] is True
    assert set(devcontainer["runServices"]) == {"postgres", "redis"}
    assert "ghcr.io/devcontainers/features/docker-in-docker:4" in devcontainer["features"]
    assert "python:1-3.12-bookworm" in dockerfile

    services = compose["services"]
    assert {"app", "postgres", "redis"}.issubset(services)
    environment = services["app"]["environment"]
    assert environment["REDIS_URL"] == "redis://redis:6379/0"
    assert "postgres:5432" in environment["DATABASE_URL"]
    assert environment["AMOSCLAUD_PLATFORM_DATABASE_URL"] == environment["DATABASE_URL"]
    assert services["app"]["environment"]["REDIS_URL"] == "redis://redis:6379/0"
    assert "postgres:5432" in services["app"]["environment"]["DATABASE_URL"]
    assert services["postgres"]["healthcheck"]
    assert services["redis"]["healthcheck"]


def test_repository_ui_handles_plain_text_errors_and_existing_publish() -> None:
    source = (ROOT / "web/github-organization-publish.js").read_text(
        encoding="utf-8"
    )
    assert "/api/v1/github/organizations" in source
    assert "/api/v1/repositories/create-real" in source
    assert "const text = await response.text()" in source
    assert "payload = text ? JSON.parse(text) : null" in source
    assert "owner: createOwnerInput.value" in source
    assert "/api/v1/github/repositories/${encodeURIComponent(publishIdInput.value)}/publish" in source
    assert "/api/v1/github/repositories/${encodeURIComponent(repositoryId)}/push" in source
    assert "Publish / push GitHub" in source
    assert "/api/v1/github/connect-organizations" in source
