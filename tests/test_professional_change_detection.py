from __future__ import annotations

import subprocess
from pathlib import Path

from amosclaud_bot.professional import _has_diff, _prepare_new_files_for_diff


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_new_file_is_made_visible_to_git_diff(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.com")
    (tmp_path / "README.md").write_text("initial\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-m", "initial")

    document = tmp_path / "docs" / "AMOSCLAUD_ACTION_TEST.md"
    document.parent.mkdir()
    document.write_text("real change\n", encoding="utf-8")

    assert _has_diff(tmp_path) is False
    assert _prepare_new_files_for_diff(tmp_path) == ["docs/AMOSCLAUD_ACTION_TEST.md"]
    assert _has_diff(tmp_path) is True
    assert "docs/AMOSCLAUD_ACTION_TEST.md" in _git(tmp_path, "diff", "--name-only").stdout


def test_protected_untracked_file_is_not_added_to_repair_diff(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    workflow = tmp_path / ".github" / "workflows" / "unsafe.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: unsafe\n", encoding="utf-8")

    assert _prepare_new_files_for_diff(tmp_path) == []
    assert _has_diff(tmp_path) is False
