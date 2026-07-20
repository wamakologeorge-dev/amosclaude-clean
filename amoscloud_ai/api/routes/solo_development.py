"""Native software-development operations for Amosclaud repositories.

This module deliberately does not call GitHub. Issues, pull requests, merges, and
repository deployment settings are stored and executed inside Amosclaud.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.repositories import (
    _access,
    _checkout,
    _current_user,
    _db,
    _open,
    _repo_lock,
    _repo_path,
    _require_write,
    _safe_branch,
)

router = APIRouter(prefix="/repositories", tags=["native-development"])


class IssueCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=50_000)
    labels: list[str] = Field(default_factory=list, max_length=20)


class IssueUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=50_000)
    state: Literal["open", "closed"] | None = None
    labels: list[str] | None = Field(default=None, max_length=20)


class PullRequestCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=50_000)
    head_branch: str = Field(min_length=1, max_length=200)
    base_branch: str = Field(default="main", min_length=1, max_length=200)


class DeploymentSettings(BaseModel):
    provider: Literal["local", "docker", "railway", "custom"] = "local"
    build_command: str = Field(default="python -m pytest -q", max_length=500)
    start_command: str = Field(default="python -m amoscloud_ai.main", max_length=500)
    healthcheck_path: str = Field(default="/health", max_length=200)
    environment: dict[str, str] = Field(default_factory=dict)
    auto_deploy_branch: str = Field(default="main", max_length=200)


def _ensure_tables(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS native_issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repository_id INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            labels_json TEXT NOT NULL DEFAULT '[]',
            state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','closed')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(repository_id) REFERENCES repositories(id) ON DELETE CASCADE,
            FOREIGN KEY(author_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS native_pull_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repository_id INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            head_branch TEXT NOT NULL,
            base_branch TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','merged','closed')),
            merge_commit TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(repository_id, head_branch, base_branch, state),
            FOREIGN KEY(repository_id) REFERENCES repositories(id) ON DELETE CASCADE,
            FOREIGN KEY(author_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    db.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _issue_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "repository_id": row["repository_id"],
        "author_id": row["author_id"],
        "title": row["title"],
        "body": row["body"],
        "labels": json.loads(row["labels_json"] or "[]"),
        "state": row["state"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _pr_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "repository_id": row["repository_id"],
        "author_id": row["author_id"],
        "title": row["title"],
        "body": row["body"],
        "head_branch": row["head_branch"],
        "base_branch": row["base_branch"],
        "state": row["state"],
        "merge_commit": row["merge_commit"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@router.post("/{repository_id}/issues", status_code=201)
def create_issue(repository_id: int, body: IssueCreate, user: sqlite3.Row = Depends(_current_user)) -> dict:
    with _db() as db:
        _ensure_tables(db)
        _access(db, repository_id, user["id"])
        now = _now()
        cursor = db.execute(
            "INSERT INTO native_issues(repository_id,author_id,title,body,labels_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (repository_id, user["id"], body.title.strip(), body.body, json.dumps(body.labels), now, now),
        )
        db.commit()
        row = db.execute("SELECT * FROM native_issues WHERE id=?", (cursor.lastrowid,)).fetchone()
        return _issue_dict(row)


@router.get("/{repository_id}/issues")
def list_issues(repository_id: int, user: sqlite3.Row = Depends(_current_user)) -> list[dict]:
    with _db() as db:
        _ensure_tables(db)
        _access(db, repository_id, user["id"])
        rows = db.execute(
            "SELECT * FROM native_issues WHERE repository_id=? ORDER BY id DESC", (repository_id,)
        ).fetchall()
        return [_issue_dict(row) for row in rows]


@router.patch("/{repository_id}/issues/{issue_id}")
def update_issue(repository_id: int, issue_id: int, body: IssueUpdate, user: sqlite3.Row = Depends(_current_user)) -> dict:
    with _db() as db:
        _ensure_tables(db)
        access = _access(db, repository_id, user["id"])
        _require_write(access)
        row = db.execute(
            "SELECT * FROM native_issues WHERE id=? AND repository_id=?", (issue_id, repository_id)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Issue not found")
        db.execute(
            "UPDATE native_issues SET title=?,body=?,labels_json=?,state=?,updated_at=? WHERE id=?",
            (
                body.title.strip() if body.title is not None else row["title"],
                body.body if body.body is not None else row["body"],
                json.dumps(body.labels) if body.labels is not None else row["labels_json"],
                body.state or row["state"],
                _now(),
                issue_id,
            ),
        )
        db.commit()
        return _issue_dict(db.execute("SELECT * FROM native_issues WHERE id=?", (issue_id,)).fetchone())


@router.post("/{repository_id}/pull-requests", status_code=201)
def create_pull_request(repository_id: int, body: PullRequestCreate, user: sqlite3.Row = Depends(_current_user)) -> dict:
    head = _safe_branch(body.head_branch)
    base = _safe_branch(body.base_branch)
    if head == base:
        raise HTTPException(status_code=422, detail="Head and base branches must differ")
    with _repo_lock(repository_id), _db() as db:
        _ensure_tables(db)
        access = _access(db, repository_id, user["id"])
        _require_write(access)
        repo = _open(repository_id)
        names = {item.name for item in repo.heads}
        if head not in names or base not in names:
            raise HTTPException(status_code=404, detail="Pull request branch not found")
        if repo.commit(head).hexsha == repo.commit(base).hexsha:
            raise HTTPException(status_code=409, detail="Branches contain no different commits")
        now = _now()
        try:
            cursor = db.execute(
                "INSERT INTO native_pull_requests(repository_id,author_id,title,body,head_branch,base_branch,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (repository_id, user["id"], body.title.strip(), body.body, head, base, now, now),
            )
            db.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="An open pull request already exists for these branches") from exc
        return _pr_dict(db.execute("SELECT * FROM native_pull_requests WHERE id=?", (cursor.lastrowid,)).fetchone())


@router.get("/{repository_id}/pull-requests")
def list_pull_requests(repository_id: int, user: sqlite3.Row = Depends(_current_user)) -> list[dict]:
    with _db() as db:
        _ensure_tables(db)
        _access(db, repository_id, user["id"])
        rows = db.execute(
            "SELECT * FROM native_pull_requests WHERE repository_id=? ORDER BY id DESC", (repository_id,)
        ).fetchall()
        return [_pr_dict(row) for row in rows]


@router.post("/{repository_id}/pull-requests/{pull_request_id}/merge")
def merge_pull_request(repository_id: int, pull_request_id: int, user: sqlite3.Row = Depends(_current_user)) -> dict:
    with _repo_lock(repository_id), _db() as db:
        _ensure_tables(db)
        access = _access(db, repository_id, user["id"])
        _require_write(access)
        row = db.execute(
            "SELECT * FROM native_pull_requests WHERE id=? AND repository_id=?",
            (pull_request_id, repository_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Pull request not found")
        if row["state"] != "open":
            raise HTTPException(status_code=409, detail="Pull request is not open")
        repo = _open(repository_id)
        _checkout(repo, row["base_branch"])
        try:
            repo.git.merge("--no-ff", row["head_branch"], "-m", f"Merge pull request #{pull_request_id}: {row['title']}")
        except Exception as exc:
            repo.git.merge("--abort")
            raise HTTPException(status_code=409, detail="Merge conflict; resolve the branches before merging") from exc
        merge_commit = repo.head.commit.hexsha
        db.execute(
            "UPDATE native_pull_requests SET state='merged',merge_commit=?,updated_at=? WHERE id=?",
            (merge_commit, _now(), pull_request_id),
        )
        db.commit()
        return _pr_dict(db.execute("SELECT * FROM native_pull_requests WHERE id=?", (pull_request_id,)).fetchone())


def _deployment_path(repository_id: int) -> Path:
    return _repo_path(repository_id) / ".amosclaud" / "deployment.json"


@router.get("/{repository_id}/deployment-settings")
def get_deployment_settings(repository_id: int, user: sqlite3.Row = Depends(_current_user)) -> dict:
    with _repo_lock(repository_id), _db() as db:
        _access(db, repository_id, user["id"])
        path = _deployment_path(repository_id)
        if not path.is_file():
            return DeploymentSettings().model_dump()
        return DeploymentSettings.model_validate_json(path.read_text(encoding="utf-8")).model_dump()


@router.put("/{repository_id}/deployment-settings")
def put_deployment_settings(repository_id: int, body: DeploymentSettings, user: sqlite3.Row = Depends(_current_user)) -> dict:
    with _repo_lock(repository_id), _db() as db:
        access = _access(db, repository_id, user["id"])
        _require_write(access)
        repo = _open(repository_id)
        _checkout(repo, access["default_branch"])
        path = _deployment_path(repository_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body.model_dump(), indent=2) + "\n", encoding="utf-8")
        repo.git.add(path.relative_to(_repo_path(repository_id)).as_posix())
        if repo.is_dirty(untracked_files=True):
            with repo.config_writer() as config:
                config.set_value("user", "name", user["name"] or user["email"])
                config.set_value("user", "email", user["email"])
            commit = repo.index.commit("Configure Amosclaud deployment").hexsha
        else:
            commit = repo.head.commit.hexsha
        return {"settings": body.model_dump(), "commit": commit}
