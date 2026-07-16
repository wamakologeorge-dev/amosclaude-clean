"""Safe Git evidence collection for Amosclaud-metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from .models import CommitRecord, RepositoryRecord


class GitMetadataError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitSnapshot:
    repository: RepositoryRecord
    commit: CommitRecord
    dirty_files: tuple[str, ...]


def _run(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    if result.returncode:
        raise GitMetadataError((result.stderr or result.stdout or "git command failed").strip())
    return result.stdout.strip()


def collect_git_snapshot(workspace: str | Path, *, objective: str, summary: str) -> GitSnapshot:
    root = Path(workspace).expanduser().resolve()
    if not (root / ".git").exists():
        raise GitMetadataError(f"Git metadata is unavailable at {root}")
    sha = _run(root, "rev-parse", "HEAD")
    branch = _run(root, "rev-parse", "--abbrev-ref", "HEAD")
    default_branch = "main"
    try:
        symbolic = _run(root, "symbolic-ref", "refs/remotes/origin/HEAD")
        default_branch = symbolic.rsplit("/", 1)[-1]
    except GitMetadataError:
        pass
    remote_url = ""
    try:
        remote_url = _run(root, "remote", "get-url", "origin")
    except GitMetadataError:
        pass
    full_name = root.name
    if remote_url:
        cleaned = remote_url.removesuffix(".git").rstrip("/")
        full_name = cleaned.split(":")[-1].split("github.com/")[-1]
    changed = tuple(
        line[3:].strip()
        for line in _run(root, "status", "--short").splitlines()
        if len(line) > 3 and line[3:].strip()
    )
    parents = tuple(_run(root, "show", "-s", "--format=%P", "HEAD").split())
    files = tuple(
        line for line in _run(root, "show", "--pretty=format:", "--name-only", "HEAD").splitlines() if line
    )
    repository = RepositoryRecord(
        full_name=full_name,
        default_branch=default_branch,
        workspace=str(root),
        remote_url=remote_url,
        commit_sha=sha,
    )
    commit = CommitRecord(
        repository=full_name,
        sha=sha,
        branch=branch,
        objective=objective,
        summary=summary,
        files_changed=files,
        parent_shas=parents,
    )
    return GitSnapshot(repository=repository, commit=commit, dirty_files=changed)
