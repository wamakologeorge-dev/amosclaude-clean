from pathlib import Path

import pytest
from fastapi import HTTPException

from repository.connector import RepositoryConnector, RepositoryConnectorError, RepositoryRecord
from repository.git_server import GitPrincipal, _authorize, _service, router


def record(tmp_path: Path) -> RepositoryRecord:
    return RepositoryRecord(
        id=1,
        owner="george",
        owner_email="george@example.com",
        name="demo",
        default_branch="main",
        is_private=True,
        storage_path=tmp_path / "george" / "demo.git",
    )


def test_connector_confines_repository_paths(tmp_path: Path):
    connector = RepositoryConnector(tmp_path)
    assert connector.storage_path("george", "demo.git") == tmp_path / "george" / "demo.git"
    with pytest.raises(RepositoryConnectorError):
        connector.storage_path("../outside", "demo")
    with pytest.raises(RepositoryConnectorError):
        connector.storage_path("george", "../../outside")


def test_git_router_exposes_fetch_and_push_contracts():
    paths = {route.path for route in router.routes}
    assert "/git/{username}/{repo_name}/info/refs" in paths
    assert "/git/{username}/{repo_name}/{service}" in paths


def test_owner_and_admin_can_access_private_repository(tmp_path: Path):
    item = record(tmp_path)
    _authorize(item, GitPrincipal("user", "george@example.com", frozenset()), write=True)
    _authorize(item, GitPrincipal("user", "admin@example.com", frozenset(), is_admin=True), write=True)


def test_unrelated_user_is_rejected(tmp_path: Path):
    with pytest.raises(HTTPException) as captured:
        _authorize(
            record(tmp_path),
            GitPrincipal("user", "other@example.com", frozenset()),
            write=False,
        )
    assert captured.value.status_code == 403


def test_service_keys_require_read_and_write_scopes(tmp_path: Path):
    item = record(tmp_path)
    _authorize(item, GitPrincipal("service-key", "agent", frozenset({"repositories:read"})), write=False)
    with pytest.raises(HTTPException):
        _authorize(item, GitPrincipal("service-key", "agent", frozenset({"repositories:read"})), write=True)
    _authorize(item, GitPrincipal("service-key", "fixer", frozenset({"repositories:write"})), write=True)


def test_only_git_smart_http_services_are_allowed():
    assert _service("git-upload-pack") == "git-upload-pack"
    assert _service("git-receive-pack") == "git-receive-pack"
    with pytest.raises(HTTPException):
        _service("shell")
