from __future__ import annotations

import time
from pathlib import Path

import pytest

from amoscloud_ai.local_cloud.authority import LocalAuthority
from amoscloud_ai.local_cloud.executor import ExecutionError, LocalJobManager
from amoscloud_ai.local_cloud.workspaces import WorkspaceRegistry


def test_authority_initializes_verifies_and_rotates(tmp_path: Path) -> None:
    authority = LocalAuthority(tmp_path / "state")
    state, token = authority.initialize()
    assert state.instance_id.startswith("local_")
    assert token is not None
    assert authority.verify(token)
    assert not authority.verify("wrong-token")
    replacement = authority.rotate()
    assert not authority.verify(token)
    assert authority.verify(replacement)


def test_workspace_registry_uses_existing_local_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AMOSCLAUD_LOCAL_ALLOWED_ROOTS", str(tmp_path))
    workspace_dir = tmp_path / "project"
    workspace_dir.mkdir()
    registry = WorkspaceRegistry(tmp_path / "state")
    workspace = registry.register(name="Project", path=str(workspace_dir))
    assert workspace.path == str(workspace_dir.resolve())
    assert registry.get(workspace.id) == workspace
    assert registry.register(name="Project", path=str(workspace_dir)) == workspace


def test_job_requires_exact_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AMOSCLAUD_LOCAL_ALLOWED_ROOTS", str(tmp_path))
    workspace_dir = tmp_path / "project"
    workspace_dir.mkdir()
    registry = WorkspaceRegistry(tmp_path / "state")
    workspace = registry.register(name="Project", path=str(workspace_dir))
    manager = LocalJobManager()
    with pytest.raises(ExecutionError):
        manager.create(workspace=workspace, action="inspect", confirmation="yes")

    confirmation = manager.required_confirmation(workspace.id, "inspect")
    job = manager.create(
        workspace=workspace,
        action="inspect",
        confirmation=confirmation,
    )
    for _ in range(100):
        if manager.get(job.id).status in {"succeeded", "failed"}:
            break
        time.sleep(0.02)
    assert manager.get(job.id).status == "succeeded"
