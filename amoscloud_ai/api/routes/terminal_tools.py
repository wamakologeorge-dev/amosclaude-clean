"""Codespace-style project tools for Amosclaud cloud workspaces.

These routes inspect and commit the actual persistent repository. Imported GitHub
repositories additionally expose authenticated pull, push, and safe sync-and-push.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.repositories import (
    _access,
    _current_user,
    _db,
    _repo_lock,
    _repo_path,
    _require_write,
    _safe_branch,
)

router = APIRouter(prefix="/cloud-workspaces", tags=["cloud-workspace-tools"])


class ToolCommitRequest(BaseModel):
    message: str = Field(
        default="Update from Amosclaud cloud terminal",
        min_length=1,
        max_length=200,
    )
    branch: str | None = Field(default=None, max_length=200)


class ToolSyncRequest(BaseModel):
    branch: str | None = Field(default=None, max_length=200)
    commit_message: str = Field(
        default="Update from Amosclaud cloud terminal",
        min_length=1,
        max_length=200,
    )


def _repository(repository_id: int, user_id: int) -> sqlite3.Row:
    with _db() as db:
        row = _access(db, repository_id, user_id)
    _require_write(row)
    return row


def _value(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    return row[key] if key in row.keys() else default


def _open_repository(repository_id: int) -> Repo:
    try:
        return Repo(_repo_path(repository_id))
    except (InvalidGitRepositoryError, OSError) as exc:
        raise HTTPException(
            status_code=409,
            detail="Repository Git storage is unavailable",
        ) from exc


def _changed_files(repo: Repo) -> tuple[list[str], list[str]]:
    try:
        lines = repo.git.status(
            "--porcelain=v1",
            "--untracked-files=all",
        ).splitlines()
    except GitCommandError as exc:
        raise HTTPException(
            status_code=409,
            detail="Unable to read repository changes",
        ) from exc
    paths: list[str] = []
    raw: list[str] = []
    for line in lines[:500]:
        if not line:
            continue
        raw.append(line)
        path = line[3:] if len(line) > 3 else line
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path.strip())
    return paths, raw


def _ahead_behind(repo: Repo, branch: str) -> tuple[int | None, int | None]:
    try:
        repo.commit(f"origin/{branch}")
    except Exception:
        return None, None
    try:
        ahead = int(repo.git.rev_list("--count", f"origin/{branch}..{branch}"))
        behind = int(repo.git.rev_list("--count", f"{branch}..origin/{branch}"))
        return ahead, behind
    except (GitCommandError, ValueError):
        return None, None


def _git_status(repository_id: int, row: sqlite3.Row) -> dict[str, Any]:
    repo = _open_repository(repository_id)
    detached = repo.head.is_detached
    branch = None if detached else repo.active_branch.name
    changed, porcelain = _changed_files(repo)
    head = repo.head.commit.hexsha if repo.head.is_valid() else None
    ahead, behind = _ahead_behind(repo, branch) if branch else (None, None)
    github_full_name = _value(row, "github_full_name")
    return {
        "repository_id": repository_id,
        "source": "github" if github_full_name else "amosclaud",
        "repository_name": str(row["name"]),
        "github_full_name": github_full_name,
        "github_url": _value(row, "github_html_url"),
        "default_branch": str(row["default_branch"] or "main"),
        "branch": branch,
        "detached": detached,
        "head": head,
        "head_short": head[:12] if head else None,
        "dirty": bool(changed),
        "changed_files": changed,
        "porcelain": porcelain,
        "ahead": ahead,
        "behind": behind,
    }


def _add_command(
    commands: list[dict[str, str]],
    command_id: str,
    label: str,
    command: str,
    description: str,
    kind: str = "command",
) -> None:
    if command and all(item["command"] != command for item in commands):
        commands.append(
            {
                "id": command_id,
                "label": label,
                "command": command,
                "description": description,
                "kind": kind,
            }
        )


def _package_scripts(path: Path) -> dict[str, str]:
    package_file = path / "package.json"
    if not package_file.is_file():
        return {}
    try:
        payload = json.loads(package_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    scripts = payload.get("scripts") if isinstance(payload, dict) else None
    if not isinstance(scripts, dict):
        return {}
    return {str(key): str(value) for key, value in scripts.items() if value}


def _make_targets(path: Path) -> set[str]:
    makefile = next(
        (item for item in (path / "Makefile", path / "makefile") if item.is_file()),
        None,
    )
    if not makefile:
        return set()
    targets: set[str] = set()
    try:
        for line in makefile.read_text(
            encoding="utf-8",
            errors="ignore",
        ).splitlines():
            if line.startswith((" ", "\t", ".")) or ":" not in line:
                continue
            target = line.split(":", 1)[0].strip()
            if target and all(
                character.isalnum() or character in "_-" for character in target
            ):
                targets.add(target)
    except OSError:
        pass
    return targets


def _smart_commands(repository_id: int) -> list[dict[str, str]]:
    path = _repo_path(repository_id)
    commands: list[dict[str, str]] = []
    _add_command(
        commands,
        "status",
        "Git status",
        "git status --short --branch",
        "Show the real branch and working-tree changes.",
        "git",
    )
    _add_command(
        commands,
        "diff",
        "Review changes",
        "git diff --stat && git diff",
        "Review actual uncommitted changes.",
        "git",
    )
    _add_command(
        commands,
        "recent",
        "Recent commits",
        "git log --oneline --decorate -12",
        "Show recent repository history.",
        "git",
    )

    scripts = _package_scripts(path)
    for script_name, label, description in (
        ("dev", "Start dev", "Start the project's development command."),
        ("start", "Run app", "Run the project's start command."),
        ("test", "Test", "Run the project's test suite."),
        ("build", "Build", "Build the project."),
        ("lint", "Lint", "Run the configured linter."),
        ("typecheck", "Type check", "Run static type checks."),
        ("format", "Format", "Run the configured formatter."),
    ):
        if script_name in scripts:
            _add_command(
                commands,
                f"npm-{script_name}",
                label,
                f"npm run {script_name}",
                description,
                "project",
            )

    make_targets = _make_targets(path)
    for target, label in (
        ("test", "Test"),
        ("build", "Build"),
        ("lint", "Lint"),
        ("dev", "Start dev"),
        ("run", "Run app"),
    ):
        if target in make_targets:
            _add_command(
                commands,
                f"make-{target}",
                label,
                f"make {target}",
                f"Run Make target {target}.",
                "project",
            )

    python_project = any(
        (path / name).is_file()
        for name in ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg")
    )
    if python_project:
        if (path / "tests").exists() or (path / "pytest.ini").is_file():
            _add_command(
                commands,
                "pytest",
                "Test",
                "python -m pytest -q",
                "Run Python tests.",
                "project",
            )
        pyproject = ""
        try:
            pyproject = (path / "pyproject.toml").read_text(encoding="utf-8")
        except OSError:
            pass
        if "[tool.ruff" in pyproject:
            _add_command(
                commands,
                "ruff",
                "Lint",
                "python -m ruff check .",
                "Run Ruff checks.",
                "project",
            )
            _add_command(
                commands,
                "ruff-format",
                "Format",
                "python -m ruff format .",
                "Format Python files with Ruff.",
                "project",
            )
        if (path / "manage.py").is_file():
            _add_command(
                commands,
                "django",
                "Run app",
                "python manage.py runserver 0.0.0.0:8000",
                "Start the Django development server.",
                "project",
            )

    if (path / "Cargo.toml").is_file():
        _add_command(
            commands,
            "cargo-test",
            "Test",
            "cargo test",
            "Run Rust tests.",
            "project",
        )
        _add_command(
            commands,
            "cargo-build",
            "Build",
            "cargo build",
            "Build the Rust project.",
            "project",
        )
        _add_command(
            commands,
            "cargo-clippy",
            "Lint",
            "cargo clippy --all-targets --all-features",
            "Run Clippy.",
            "project",
        )
    if (path / "go.mod").is_file():
        _add_command(
            commands,
            "go-test",
            "Test",
            "go test ./...",
            "Run Go tests.",
            "project",
        )
        _add_command(
            commands,
            "go-build",
            "Build",
            "go build ./...",
            "Build Go packages.",
            "project",
        )
    if (path / "docker-compose.yml").is_file() or (path / "compose.yml").is_file():
        _add_command(
            commands,
            "compose-config",
            "Check Compose",
            "docker compose config",
            "Validate Docker Compose configuration.",
            "project",
        )

    return commands[:16]


@router.get("/repositories/{repository_id}/tools")
def project_tools(
    repository_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    row = _repository(repository_id, int(user["id"]))
    status = _git_status(repository_id, row)
    return {
        "repository": {
            "id": repository_id,
            "name": row["name"],
            "source": status["source"],
            "github_full_name": status["github_full_name"],
            "github_url": status["github_url"],
        },
        "status": status,
        "commands": _smart_commands(repository_id),
        "actions": {
            "commit": True,
            "pull": status["source"] == "github",
            "push": status["source"] == "github",
            "sync_push": status["source"] == "github",
            "run": True,
            "debug": True,
            "ports": True,
            "problems": True,
            "connectors": True,
            "network": True,
            "native_saved_immediately": status["source"] == "amosclaud",
        },
    }


@router.post("/repositories/{repository_id}/tools/commit")
def commit_project_changes(
    repository_id: int,
    body: ToolCommitRequest,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    row = _repository(repository_id, int(user["id"]))
    with _repo_lock(repository_id):
        repo = _open_repository(repository_id)
        active = None if repo.head.is_detached else repo.active_branch.name
        branch = _safe_branch(
            body.branch or active or row["default_branch"] or "main"
        )
        changed, _ = _changed_files(repo)
        if changed and active and active != branch:
            raise HTTPException(
                status_code=409,
                detail=f"Checkout branch '{branch}' before committing its workspace changes",
            )
        if not active or active != branch:
            try:
                repo.git.checkout(branch)
            except GitCommandError as exc:
                raise HTTPException(
                    status_code=409,
                    detail=f"Branch '{branch}' is unavailable",
                ) from exc
        if not changed:
            commit = repo.head.commit.hexsha if repo.head.is_valid() else None
            return {
                "repository_id": repository_id,
                "branch": branch,
                "commit": commit,
                "no_changes": True,
                "source": (
                    "github" if _value(row, "github_full_name") else "amosclaud"
                ),
                "message": "No uncommitted changes were found.",
            }
        repo.git.add(A=True)
        with repo.config_writer() as config:
            config.set_value("user", "name", user["name"] or user["email"])
            config.set_value("user", "email", user["email"])
        commit = repo.index.commit(body.message.strip()).hexsha
    return {
        "repository_id": repository_id,
        "branch": branch,
        "commit": commit,
        "no_changes": False,
        "changed_files": changed,
        "source": "github" if _value(row, "github_full_name") else "amosclaud",
        "push_available": bool(_value(row, "github_full_name")),
        "message": f"Committed {len(changed)} changed file(s).",
    }


@router.post("/repositories/{repository_id}/tools/pull")
def pull_project_changes(
    repository_id: int,
    body: ToolSyncRequest,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    row = _repository(repository_id, int(user["id"]))
    if not _value(row, "github_full_name"):
        raise HTTPException(
            status_code=409,
            detail="This is an Amosclaud-native repository; there is no GitHub remote to pull",
        )
    from amoscloud_ai.api.routes.github_repositories import (
        GitHubSyncRequest,
        pull_github_repository,
    )

    return pull_github_repository(
        repository_id,
        GitHubSyncRequest(
            branch=body.branch,
            commit_message=body.commit_message,
        ),
        user,
    )


@router.post("/repositories/{repository_id}/tools/push")
def push_project_changes(
    repository_id: int,
    body: ToolSyncRequest,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    row = _repository(repository_id, int(user["id"]))
    if not _value(row, "github_full_name"):
        raise HTTPException(
            status_code=409,
            detail="Amosclaud-native repository changes are already stored on the platform",
        )
    from amoscloud_ai.api.routes.github_repositories import (
        GitHubSyncRequest,
        push_github_repository,
    )

    return push_github_repository(
        repository_id,
        GitHubSyncRequest(
            branch=body.branch,
            commit_message=body.commit_message,
        ),
        user,
    )


@router.post("/repositories/{repository_id}/tools/sync-push")
def sync_push_project_changes(
    repository_id: int,
    body: ToolSyncRequest,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    """Commit, fetch, safely rebase, and push one GitHub-backed branch.

    This never force-pushes. Rebase conflicts are aborted and returned to the user
    so no remote history or local conflict state is silently overwritten.
    """

    row = _repository(repository_id, int(user["id"]))
    if not _value(row, "github_full_name"):
        raise HTTPException(
            status_code=409,
            detail="Amosclaud-native repository changes are already stored on the platform",
        )

    from amoscloud_ai.api.routes.github_repositories import (
        _connection,
        _decrypt_token,
    )
    from amoscloud_ai.github_git_auth import authenticated_git

    with _db() as db:
        connection = _connection(db, int(user["id"]))
        token = _decrypt_token(connection["access_token_ciphertext"])

    rebased = False
    committed_files: list[str] = []
    with _repo_lock(repository_id):
        repo = _open_repository(repository_id)
        active = None if repo.head.is_detached else repo.active_branch.name
        branch = _safe_branch(
            body.branch
            or active
            or _value(row, "github_default_branch")
            or row["default_branch"]
            or "main"
        )
        if branch not in {head.name for head in repo.heads}:
            raise HTTPException(
                status_code=409,
                detail=f"Local branch '{branch}' does not exist",
            )

        committed_files, _ = _changed_files(repo)
        if committed_files and active != branch:
            raise HTTPException(
                status_code=409,
                detail="Checkout the requested branch before synchronizing workspace changes",
            )
        if active != branch:
            try:
                repo.git.checkout(branch)
            except GitCommandError as exc:
                raise HTTPException(
                    status_code=409,
                    detail=f"Branch '{branch}' could not be checked out",
                ) from exc

        if committed_files:
            repo.git.add(A=True)
            with repo.config_writer() as config:
                config.set_value("user", "name", user["name"] or user["email"])
                config.set_value("user", "email", user["email"])
            repo.index.commit(body.commit_message.strip())

        try:
            with authenticated_git(repo, token):
                repo.git.fetch("--prune", "origin")
        except GitCommandError as exc:
            raise HTTPException(
                status_code=409,
                detail="GitHub synchronization could not fetch the remote repository",
            ) from exc

        remote_ref = f"origin/{branch}"
        remote_exists = any(ref.name == remote_ref for ref in repo.remote("origin").refs)
        if remote_exists:
            _, behind = _ahead_behind(repo, branch)
            if behind:
                try:
                    repo.git.rebase(remote_ref)
                    rebased = True
                except GitCommandError as exc:
                    try:
                        repo.git.rebase("--abort")
                    except GitCommandError:
                        pass
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Sync & Push stopped because remote changes conflict with "
                            "local commits. Resolve the conflict in the terminal, then retry."
                        ),
                    ) from exc

        try:
            with authenticated_git(repo, token):
                push_info = repo.remote("origin").push(
                    refspec=f"refs/heads/{branch}:refs/heads/{branch}"
                )
            if any(getattr(item, "flags", 0) & item.ERROR for item in push_info):
                raise GitCommandError("push", 1)
        except GitCommandError as exc:
            raise HTTPException(
                status_code=409,
                detail=(
                    "GitHub rejected Sync & Push. No force push was attempted; "
                    "check branch protection or repository permissions."
                ),
            ) from exc

        commit = repo.commit(branch).hexsha
        ahead, behind = _ahead_behind(repo, branch)

    now = datetime.now(timezone.utc).isoformat()
    with _db() as db:
        db.execute(
            """UPDATE repositories
               SET updated_at=?,github_last_sync_at=?,github_last_sync_attempt_at=?
               WHERE id=?""",
            (now, now, now, repository_id),
        )
        db.commit()

    return {
        "repository_id": repository_id,
        "branch": branch,
        "commit": commit,
        "synced_at": now,
        "synchronized": True,
        "force_push": False,
        "rebased": rebased,
        "committed_files": committed_files,
        "ahead": ahead,
        "behind": behind,
    }
