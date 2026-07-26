"""Safe GitHub-to-Amosclaud synchronization for signed push webhooks."""

from __future__ import annotations

from datetime import datetime, timezone

from git import Repo
from git.exc import GitCommandError

from amoscloud_ai.api.routes.github_repositories import (
    _authenticated_clone_url,
    _connection,
    _db,
    _decrypt_token,
    _public_remote_url,
)
from amoscloud_ai.api.routes.repositories import _repo_lock, _repo_path

_SYNC_COLUMNS = {
    "github_sync_state": "TEXT",
    "github_sync_detail": "TEXT",
    "github_last_remote_sha": "TEXT",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_sync_columns() -> None:
    """Add sync evidence fields without requiring a separate migration process."""

    with _db() as db:
        columns = {
            row[1] for row in db.execute("PRAGMA table_info(repositories)").fetchall()
        }
        for name, sql_type in _SYNC_COLUMNS.items():
            if name not in columns:
                db.execute(f"ALTER TABLE repositories ADD COLUMN {name} {sql_type}")
        db.commit()


def _record(repository_id: int, state: str, detail: str, remote_sha: str | None) -> None:
    ensure_sync_columns()
    now = _now()
    with _db() as db:
        db.execute(
            """UPDATE repositories
               SET github_sync_state=?, github_sync_detail=?, github_last_remote_sha=?,
                   github_last_sync_at=?, updated_at=?
               WHERE id=?""",
            (state, detail[:1000], remote_sha, now, now, repository_id),
        )
        db.commit()


def sync_status(repository_id: int, owner_id: int) -> dict:
    ensure_sync_columns()
    with _db() as db:
        row = db.execute(
            """SELECT id,github_full_name,github_last_sync_at,github_sync_state,
                      github_sync_detail,github_last_remote_sha
               FROM repositories WHERE id=? AND owner_id=?""",
            (repository_id, owner_id),
        ).fetchone()
    if not row:
        return {}
    return dict(row)


def synchronize_github_push(
    repository_full_name: str,
    ref: str,
    remote_sha: str | None,
) -> list[dict]:
    """Fast-forward mapped workspaces after a GitHub push.

    Dirty, ahead, or diverged local work is never reset or overwritten.
    """

    if not ref.startswith("refs/heads/"):
        return []
    branch = ref.removeprefix("refs/heads/").strip()
    if not repository_full_name or not branch:
        return []

    ensure_sync_columns()
    with _db() as db:
        rows = db.execute(
            "SELECT * FROM repositories WHERE github_full_name=?",
            (repository_full_name,),
        ).fetchall()

    results: list[dict] = []
    for row in rows:
        repository_id = int(row["id"])
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
                        "Local workspace has uncommitted changes; automatic pull was blocked"
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

                remote = repo.remote("origin")
                original_url = remote.url
                try:
                    remote.set_url(
                        _authenticated_clone_url(repository_full_name, token)
                    )
                    remote.fetch(branch)
                finally:
                    remote.set_url(
                        original_url or _public_remote_url(repository_full_name)
                    )

                remote_ref = repo.commit(f"origin/{branch}")
                if branch not in [head.name for head in repo.heads]:
                    local_head = repo.create_head(branch, remote_ref)
                    local_head.checkout()
                    detail = "Created local branch from GitHub push"
                    _record(repository_id, "synced", detail, remote_ref.hexsha)
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
                    _record(repository_id, "current", detail, remote_ref.hexsha)
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
                        "Local history is ahead or diverged; automatic pull was blocked"
                    )
                    _record(repository_id, "conflict", detail, remote_ref.hexsha)
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
                _record(repository_id, "synced", detail, remote_ref.hexsha)
                results.append(
                    {
                        "repository_id": repository_id,
                        "state": "synced",
                        "detail": detail,
                    }
                )
            except (GitCommandError, ValueError, OSError) as exc:
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
