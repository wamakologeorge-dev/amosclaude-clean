"""Safe GitHub-to-Amosclaud synchronization for signed push webhooks."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException
from git import Repo
from git.exc import GitCommandError

from amoscloud_ai.api.routes.github_repositories import (
    _connection,
    _db,
    _decrypt_token,
)
from amoscloud_ai.api.routes.repositories import (
    _db as _repository_db,
    _repo_lock,
    _repo_path,
)
from amoscloud_ai.db_migrations import ensure_github_repository_schema
from amoscloud_ai.github_git_auth import authenticated_git

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_sync_columns() -> None:
    """Initialize the canonical repository and synchronization schema."""

    with _repository_db():
        pass
    with _db() as db:
        ensure_github_repository_schema(db)
        db.commit()


def _record(
    repository_id: int,
    state: str,
    detail: str,
    remote_sha: str | None,
    *,
    successful: bool = False,
) -> None:
    ensure_sync_columns()
    now = _now()
    assignments = [
        "github_sync_state=?",
        "github_sync_detail=?",
        "github_last_remote_sha=?",
        "github_last_sync_attempt_at=?",
        "updated_at=?",
    ]
    values: list[object] = [
        state,
        detail[:1000],
        remote_sha,
        now,
        now,
    ]
    if successful:
        assignments.append("github_last_sync_at=?")
        values.append(now)
    values.append(repository_id)
    with _db() as db:
        db.execute(
            f"UPDATE repositories SET {', '.join(assignments)} WHERE id=?",
            values,
        )
        db.commit()


def sync_status(repository_id: int, owner_id: int) -> dict:
    ensure_sync_columns()
    with _db() as db:
        row = db.execute(
            """SELECT id,github_full_name,github_last_sync_at,
                      github_last_sync_attempt_at,github_sync_state,
                      github_sync_detail,github_last_remote_sha
               FROM repositories WHERE id=? AND owner_id=?""",
            (repository_id, owner_id),
        ).fetchone()
    if not row:
        return {}
    return dict(row)


def _synchronization_remote(repo: Repo):
    names = {remote.name for remote in repo.remotes}
    if "origin" in names:
        return repo.remote("origin")
    if "amosclaud-publish" in names:
        return repo.remote("amosclaud-publish")
    raise ValueError("No GitHub synchronization remote is configured")


def _detached_head_is_referenced(repo: Repo) -> bool:
    if not repo.head.is_detached:
        return True
    detached = repo.head.commit
    for head in repo.heads:
        if detached.hexsha == head.commit.hexsha:
            return True
        if repo.is_ancestor(detached, head.commit):
            return True
    return False


def _mapped_rows(
    repository_full_name: str,
    github_repository_id: int | None,
):
    ensure_sync_columns()
    with _db() as db:
        if github_repository_id:
            return db.execute(
                """SELECT * FROM repositories
                   WHERE github_repository_id=?
                      OR (github_repository_id IS NULL
                          AND github_full_name=? COLLATE NOCASE)""",
                (github_repository_id, repository_full_name),
            ).fetchall()
        return db.execute(
            """SELECT * FROM repositories
               WHERE github_full_name=? COLLATE NOCASE""",
            (repository_full_name,),
        ).fetchall()


def _refresh_mapping(
    repository_id: int,
    repository_full_name: str,
    github_repository_id: int | None,
) -> None:
    if not github_repository_id:
        return
    with _db() as db:
        db.execute(
            """UPDATE repositories
               SET github_repository_id=?, github_full_name=?
               WHERE id=?""",
            (github_repository_id, repository_full_name, repository_id),
        )
        db.commit()


def _synchronize_github_push(
    repository_full_name: str,
    ref: str,
    remote_sha: str | None,
    github_repository_id: int | None = None,
) -> list[dict]:
    """Fast-forward mapped workspaces after a GitHub push.

    Dirty, detached-unreferenced, ahead, or diverged local work is never reset
    or overwritten. One stale user's GitHub authorization cannot stop another
    mapped workspace from synchronizing.
    """

    if not ref.startswith("refs/heads/"):
        return []
    branch = ref.removeprefix("refs/heads/").strip()
    if not repository_full_name or not branch:
        return []

    rows = _mapped_rows(repository_full_name, github_repository_id)
    results: list[dict] = []
    for row in rows:
        repository_id = int(row["id"])
        _refresh_mapping(
            repository_id,
            repository_full_name,
            github_repository_id,
        )
        expected_branch = str(
            row["github_default_branch"] or row["default_branch"] or "main"
        )
        if branch != expected_branch:
            results.append(
                {
                    "repository_id": repository_id,
                    "state": "ignored",
                    "detail": (
                        f"Push branch {branch} is not mapped default branch "
                        f"{expected_branch}"
                    ),
                }
            )
            continue

        with _repo_lock(repository_id):
            try:
                with _db() as db:
                    connection = _connection(db, int(row["owner_id"]))
                    token = _decrypt_token(connection["access_token_ciphertext"])

                repo = Repo(_repo_path(repository_id))
                if repo.is_dirty(untracked_files=True):
                    detail = (
                        "Local workspace has uncommitted changes; "
                        "automatic pull was blocked"
                    )
                    _record(repository_id, "conflict", detail, remote_sha)
                    results.append(
                        {
                            "repository_id": repository_id,
                            "state": "conflict",
                            "detail": detail,
                        }
                    )
                    continue

                if not _detached_head_is_referenced(repo):
                    detail = (
                        "Detached HEAD contains unreferenced committed work; "
                        "automatic pull was blocked"
                    )
                    _record(repository_id, "conflict", detail, remote_sha)
                    results.append(
                        {
                            "repository_id": repository_id,
                            "state": "conflict",
                            "detail": detail,
                        }
                    )
                    continue

                remote = _synchronization_remote(repo)
                remote_name = remote.name
                with authenticated_git(repo, token):
                    remote.fetch(branch)

                remote_ref = repo.commit(f"{remote_name}/{branch}")
                if branch not in {head.name for head in repo.heads}:
                    local_head = repo.create_head(branch, remote_ref)
                    local_head.checkout()
                    detail = "Created local branch from GitHub push"
                    _record(
                        repository_id,
                        "synced",
                        detail,
                        remote_ref.hexsha,
                        successful=True,
                    )
                    results.append(
                        {
                            "repository_id": repository_id,
                            "state": "synced",
                            "detail": detail,
                        }
                    )
                    continue

                local_ref = repo.commit(branch)
                if local_ref.hexsha == remote_ref.hexsha:
                    detail = "Workspace already matches GitHub"
                    _record(
                        repository_id,
                        "current",
                        detail,
                        remote_ref.hexsha,
                        successful=True,
                    )
                    results.append(
                        {
                            "repository_id": repository_id,
                            "state": "current",
                            "detail": detail,
                        }
                    )
                    continue

                if not repo.is_ancestor(local_ref, remote_ref):
                    detail = (
                        "Local history is ahead or diverged; "
                        "automatic pull was blocked"
                    )
                    _record(
                        repository_id,
                        "conflict",
                        detail,
                        remote_ref.hexsha,
                    )
                    results.append(
                        {
                            "repository_id": repository_id,
                            "state": "conflict",
                            "detail": detail,
                        }
                    )
                    continue

                repo.git.checkout(branch)
                repo.head.reset(remote_ref, index=True, working_tree=True)
                detail = f"Fast-forwarded {branch} to {remote_ref.hexsha[:12]}"
                _record(
                    repository_id,
                    "synced",
                    detail,
                    remote_ref.hexsha,
                    successful=True,
                )
                results.append(
                    {
                        "repository_id": repository_id,
                        "state": "synced",
                        "detail": detail,
                    }
                )
            except (
                GitCommandError,
                HTTPException,
                ValueError,
                OSError,
            ) as exc:
                detail = f"Automatic GitHub pull failed: {type(exc).__name__}"
                _record(repository_id, "error", detail, remote_sha)
                results.append(
                    {
                        "repository_id": repository_id,
                        "state": "error",
                        "detail": detail,
                    }
                )
    return results


def synchronize_github_push(
    repository_full_name: str,
    ref: str,
    remote_sha: str | None,
    github_repository_id: int | None = None,
) -> list[dict]:
    """Run webhook synchronization without leaking background-task errors."""

    try:
        return _synchronize_github_push(
            repository_full_name,
            ref,
            remote_sha,
            github_repository_id,
        )
    except Exception as exc:  # pragma: no cover - final background-task boundary
        log.exception(
            "GitHub background synchronization failed for %s (%s)",
            repository_full_name,
            type(exc).__name__,
        )
        return [
            {
                "repository_id": None,
                "state": "error",
                "detail": f"Automatic GitHub pull failed: {type(exc).__name__}",
            }
        ]
