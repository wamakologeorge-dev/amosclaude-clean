from pathlib import Path

import pytest

from amoscloud_ai.workspace_control import (
    WorkspaceError,
    discover_layout,
    ensure_layout,
)


def test_discovers_packaged_workspace(tmp_path: Path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "docker-compose.selfhost.yml").touch()
    layout = discover_layout(app)
    assert layout.root == tmp_path
    assert layout.projects == tmp_path / "workspace" / "projects"
    ensure_layout(layout)
    assert layout.logs.is_dir()
    assert layout.projects.is_dir()


def test_discovers_source_workspace_without_reorganizing_it(tmp_path: Path):
    (tmp_path / "docker-compose.selfhost.yml").touch()
    layout = discover_layout(tmp_path)
    assert layout.app == tmp_path
    assert layout.projects == tmp_path / "AmosclaudWorkspace"


def test_rejects_unrelated_folder(tmp_path: Path):
    with pytest.raises(WorkspaceError):
        discover_layout(tmp_path)
