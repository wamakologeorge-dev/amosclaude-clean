"""Safe Git evidence collection for Amosclaud-metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from .models import CommitRecord, RepositoryRecord


class GitMetadataError(RuntimeError):
    """Raised when repository evidence cannot be collected safely."""


@dataclass(frozen=True)
class GitSnapshot:
    """Point-in-time evidence collected from a Git repository.

    Attributes:
        repository: Repository identity and HEAD SHA at collection time.
        commit: Commit details including changed files and parent SHAs.
        dirty_files: Working-tree paths that are modified but not committed,
            as reported by ``git status --short``. Empty when the tree is clean.
    """

    repository: RepositoryRecord
    commit: CommitRecord
    dirty_files: tuple[str, ...]


def _run(root: Path, *args: str) -> str:
    """Run a git sub-command in ``root`` and return trimmed stdout.

    Args:
        root: Working directory for the git process.
        *args: Arguments passed to ``git`` after the executable name.

    Returns:
        Trimmed stdout from the command.

    Raises:
        GitMetadataError: If the git process exits with a non-zero code,
            with stderr (or stdout) as the error detail.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    if result.returncode:
        detail = result.stderr or result.stdout or "git command failed"
        raise GitMetadataError(detail.strip())
    return result.stdout.strip()


def collect_git_snapshot(
    workspace: str | Path,
    *,
    objective: str,
    summary: str,
) -> GitSnapshot:
    """Collect repository and commit evidence without changing the workspace.

    Resolves the remote URL, default branch, HEAD SHA, changed files, and
    parent SHAs using read-only git commands. The remote URL is used to derive
    the ``owner/repo`` full name; falls back to the directory name when absent.

    Args:
        workspace: Path to the local repository root (must contain a ``.git`` dir).
        objective: The agent objective associated with this snapshot.
        summary: Human-readable description of the work being recorded.

    Returns:
        A :class:`GitSnapshot` with populated
        :class:`~amosclaud_metadata.models.RepositoryRecord` and
        :class:`~amosclaud_metadata.models.CommitRecord`.

    Raises:
        GitMetadataError: If ``workspace`` is not a git repository, or if any
            required git command fails.
    """
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
    parents = tuple(
        _run(root, "show", "-s", "--format=%P", "HEAD").split()
    )
    files = tuple(
        line
        for line in _run(
            root,
            "show",
            "--pretty=format:",
            "--name-only",
            "HEAD",
        ).splitlines()
        if line
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
    return GitSnapshot(
        repository=repository,
        commit=commit,
        dirty_files=changed,
    )
