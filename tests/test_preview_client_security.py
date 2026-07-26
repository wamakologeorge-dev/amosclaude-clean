from pathlib import Path

import pytest

from amoscloud_ai.preview_client import PreviewPublishError, _static_archive


def test_preview_client_packages_only_static_files(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>ready</h1>", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('ready')", encoding="utf-8")

    archive = _static_archive(tmp_path)

    assert archive.startswith(b"PK")


def test_preview_client_rejects_non_static_files(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>ready</h1>", encoding="utf-8")
    (tmp_path / "server.py").write_text("print('must not execute')", encoding="utf-8")

    with pytest.raises(PreviewPublishError):
        _static_archive(tmp_path)


def test_preview_client_rejects_symlinks(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>ready</h1>", encoding="utf-8")
    target = tmp_path / "target.js"
    target.write_text("safe", encoding="utf-8")
    link = tmp_path / "linked.js"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    with pytest.raises(PreviewPublishError):
        _static_archive(tmp_path)
