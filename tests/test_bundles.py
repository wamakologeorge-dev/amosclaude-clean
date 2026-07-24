from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from amoscloud_ai.bundles import BUNDLE_FORMAT, BundleError, build_bundle


def test_build_bundle_creates_manifest_and_excludes_secrets(tmp_path: Path):
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    workspace.mkdir()
    (workspace / "app.py").write_text("print('ready')\n", encoding="utf-8")
    (workspace / "README.md").write_text("# Example\n", encoding="utf-8")
    (workspace / ".env").write_text("SECRET=never-package\n", encoding="utf-8")
    (workspace / ".git").mkdir()
    (workspace / ".git" / "config").write_text("private\n", encoding="utf-8")

    artifact = build_bundle(
        workspace_root=workspace,
        output_root=output,
        user_id=1,
        name="example",
        version="1.0.0",
        bundle_type="source",
    )

    assert artifact.archive_path.exists()
    assert artifact.manifest.format == BUNDLE_FORMAT
    assert artifact.manifest.archive_sha256
    assert {item.path for item in artifact.manifest.files} == {"README.md", "app.py"}

    with zipfile.ZipFile(artifact.archive_path) as archive:
        names = set(archive.namelist())
        assert "bundle.json" in names
        assert "payload/app.py" in names
        assert "payload/README.md" in names
        assert "payload/.env" not in names
        assert not any(name.startswith("payload/.git/") for name in names)
        manifest = json.loads(archive.read("bundle.json"))
        assert manifest["name"] == "example"
        assert manifest["created_by"] == 1


def test_bundle_rejects_source_outside_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "app.py").write_text("pass\n", encoding="utf-8")

    with pytest.raises(BundleError, match="inside the Amosclaud workspace"):
        build_bundle(
            workspace_root=workspace,
            output_root=tmp_path / "output",
            user_id=1,
            name="escape",
            version="1.0.0",
            bundle_type="source",
            source_path="../outside",
        )
