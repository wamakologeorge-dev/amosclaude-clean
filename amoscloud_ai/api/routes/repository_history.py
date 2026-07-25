"""Per-file history and blame for native Amosclaud repositories.

These endpoints read only the repository's real stored git history. Blame is
computed with git's own line attribution (``git blame``) over the committed
revisions of the requested path, so every attributed line points at the commit
that genuinely last changed it. No attribution is fabricated: when a file is
binary, too large, or not tracked on the branch, the response says so plainly.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from amoscloud_ai.api.routes.repositories import (
    _access,
    _current_user,
    _db,
    _open,
    _repo_lock,
    _safe_branch,
    _safe_relative,
)

router = APIRouter(prefix="/repositories", tags=["repository-history"])

# Files larger than this are not annotated line-by-line; we refuse honestly
# rather than streaming megabytes of markup to the browser.
MAX_BLAME_BYTES = 1_000_000


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _commit_summary(commit: Any) -> dict:
    return {
        "sha": commit.hexsha,
        "short_sha": commit.hexsha[:7],
        "author": commit.author.name,
        "email": commit.author.email,
        "message": commit.message.strip(),
        "created_at": _iso(commit.committed_date),
    }


def _require_branch(repo: Any, branch: str) -> None:
    if branch not in [head.name for head in repo.heads]:
        raise HTTPException(status_code=404, detail="Branch not found")


def _lookup_blob(repo: Any, branch: str, path: str) -> Any | None:
    try:
        return repo.commit(branch).tree / path
    except KeyError:
        return None


def _unblamable_reason(blob: Any) -> str | None:
    if blob.size > MAX_BLAME_BYTES:
        return "This file is too large to annotate line by line."
    if b"\x00" in blob.data_stream.read():
        return "Binary files cannot be annotated."
    return None


def _blame_lines(repo: Any, branch: str, path: str) -> list[dict]:
    result: list[dict] = []
    number = 0
    for commit, lines in repo.blame(branch, path):
        for text in lines:
            number += 1
            result.append(
                {
                    "line": number,
                    "content": text,
                    "sha": commit.hexsha,
                    "short_sha": commit.hexsha[:7],
                    "author": commit.author.name,
                    "date": _iso(commit.committed_date),
                }
            )
    return result


@router.get("/{repository_id}/history")
def file_history(
    repository_id: int,
    path: str = Query(..., min_length=1, max_length=500),
    branch: str = Query("main"),
    limit: int = Query(50, ge=1, le=200),
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    """Commits that touched ``path`` on ``branch``, newest first."""
    relative = _safe_relative(path)
    safe = _safe_branch(branch)
    with _repo_lock(repository_id), _db() as db:
        _access(db, repository_id, user["id"])
        repo = _open(repository_id)
        _require_branch(repo, safe)
        commits = list(
            repo.iter_commits(safe, paths=relative.as_posix(), max_count=limit)
        )
        return {
            "path": relative.as_posix(),
            "branch": safe,
            "commits": [_commit_summary(commit) for commit in commits],
        }


@router.get("/{repository_id}/blame")
def file_blame(
    repository_id: int,
    path: str = Query(..., min_length=1, max_length=500),
    branch: str = Query("main"),
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    """Per-line attribution for a tracked text file on ``branch``."""
    relative = _safe_relative(path)
    safe = _safe_branch(branch)
    with _repo_lock(repository_id), _db() as db:
        _access(db, repository_id, user["id"])
        repo = _open(repository_id)
        _require_branch(repo, safe)
        blob = _lookup_blob(repo, safe, relative.as_posix())
        if blob is None:
            raise HTTPException(status_code=404, detail="File not found")
        reason = _unblamable_reason(blob)
        if reason:
            return {
                "path": relative.as_posix(),
                "branch": safe,
                "available": False,
                "reason": reason,
                "lines": [],
            }
        return {
            "path": relative.as_posix(),
            "branch": safe,
            "available": True,
            "reason": None,
            "lines": _blame_lines(repo, safe, relative.as_posix()),
        }
