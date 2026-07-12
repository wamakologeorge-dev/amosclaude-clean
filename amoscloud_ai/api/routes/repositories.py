"""Native repository hosting for Amosclaud platform users."""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response
from git import Repo
from git.exc import InvalidGitRepositoryError
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import DB_PATH, get_user_from_session

router = APIRouter(prefix="/repositories", tags=["repositories"])

REPOSITORY_ROOT = Path(os.getenv("REPOSITORY_STORAGE_PATH", "data/repositories"))
MAX_REPOSITORIES_PER_USER = int(os.getenv("MAX_REPOSITORIES_PER_USER", "10"))
MAX_REPOSITORY_BYTES = int(os.getenv("MAX_REPOSITORY_BYTES", str(500 * 1024 * 1024)))
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_LOCKS: dict[int, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


class RepositoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    visibility: Literal["private", "public"] = "private"
    initialize_readme: bool = True


class RepositoryResponse(BaseModel):
    id: int
    name: str
    description: str
    visibility: str
    default_branch: str
    owner_id: int
    owner_name: str
    role: str
    created_at: str
    updated_at: str


class FileWriteRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=500)
    content: str = Field(default="", max_length=2_000_000)
    branch: str = "main"
    commit_message: str = Field(default="Update file", min_length=1, max_length=200)


class FileMoveRequest(BaseModel):
    source_path: str = Field(..., min_length=1, max_length=500)
    destination_path: str = Field(..., min_length=1, max_length=500)
    branch: str = "main"
    commit_message: str = Field(default="Move file", min_length=1, max_length=200)


class FileDeleteRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=500)
    branch: str = "main"
    commit_message: str = Field(default="Delete file", min_length=1, max_length=200)


class BranchCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    source_branch: str = "main"


class CollaboratorRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    role: Literal["developer", "viewer"] = "developer"


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS repositories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            name TEXT NOT NULL COLLATE NOCASE,
            description TEXT NOT NULL DEFAULT '',
            visibility TEXT NOT NULL DEFAULT 'private',
            default_branch TEXT NOT NULL DEFAULT 'main',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(owner_id, name),
            FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS repository_collaborators (
            repository_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('developer','viewer')),
            created_at TEXT NOT NULL,
            PRIMARY KEY(repository_id, user_id),
            FOREIGN KEY(repository_id) REFERENCES repositories(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    db.commit()
    return db


def _current_user(amos_session: str | None = Cookie(default=None)) -> sqlite3.Row:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _repo_lock(repository_id: int) -> threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(repository_id, threading.RLock())


def _repo_path(repository_id: int) -> Path:
    return REPOSITORY_ROOT / str(repository_id)


def _safe_relative(value: str) -> Path:
    cleaned = value.strip().replace("\\", "/").strip("/")
    path = Path(cleaned)
    if not cleaned or path.is_absolute() or ".." in path.parts or path.parts[0] == ".git":
        raise HTTPException(status_code=422, detail="Invalid file path")
    return path


def _safe_branch(value: str) -> str:
    branch = value.strip()
    if not _BRANCH_RE.fullmatch(branch) or ".." in branch or "//" in branch or branch.endswith("/"):
        raise HTTPException(status_code=422, detail="Invalid branch name")
    return branch


def _size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _access(db: sqlite3.Connection, repository_id: int, user_id: int) -> sqlite3.Row:
    row = db.execute(
        """SELECT r.*, u.name AS owner_name,
            CASE WHEN r.owner_id = ? THEN 'owner' ELSE c.role END AS role
           FROM repositories r
           JOIN users u ON u.id = r.owner_id
           LEFT JOIN repository_collaborators c ON c.repository_id = r.id AND c.user_id = ?
           WHERE r.id = ? AND (r.owner_id = ? OR c.user_id = ? OR r.visibility = 'public')""",
        (user_id, user_id, repository_id, user_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Repository not found")
    return row


def _require_write(row: sqlite3.Row) -> None:
    if row["role"] not in {"owner", "developer"}:
        raise HTTPException(status_code=403, detail="Write access required")


def _require_owner(row: sqlite3.Row) -> None:
    if row["role"] != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")


def _response(row: sqlite3.Row) -> RepositoryResponse:
    return RepositoryResponse(
        id=row["id"], name=row["name"], description=row["description"],
        visibility=row["visibility"], default_branch=row["default_branch"],
        owner_id=row["owner_id"], owner_name=row["owner_name"],
        role=row["role"] or "viewer", created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _open(repository_id: int) -> Repo:
    try:
        return Repo(_repo_path(repository_id))
    except (InvalidGitRepositoryError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Repository storage is damaged") from exc


def _checkout(repo: Repo, branch: str) -> None:
    branch = _safe_branch(branch)
    if branch not in [head.name for head in repo.heads]:
        raise HTTPException(status_code=404, detail="Branch not found")
    repo.git.reset("--hard")
    repo.git.clean("-fd")
    repo.git.checkout(branch)


def _commit(repo: Repo, message: str, user: sqlite3.Row) -> str:
    repo.git.add(A=True)
    if not repo.is_dirty(untracked_files=True):
        raise HTTPException(status_code=409, detail="No file changes to commit")
    with repo.config_writer() as config:
        config.set_value("user", "name", user["name"] or user["email"])
        config.set_value("user", "email", user["email"])
    return repo.index.commit(message.strip()).hexsha


@router.post("", response_model=RepositoryResponse, status_code=201)
def create_repository(body: RepositoryCreate, user: sqlite3.Row = Depends(_current_user)) -> RepositoryResponse:
    name = body.name.strip()
    if not _NAME_RE.fullmatch(name):
        raise HTTPException(status_code=422, detail="Invalid repository name")
    now = datetime.now(timezone.utc).isoformat()
    with _db() as db:
        if db.execute("SELECT COUNT(*) FROM repositories WHERE owner_id = ?", (user["id"],)).fetchone()[0] >= MAX_REPOSITORIES_PER_USER:
            raise HTTPException(status_code=403, detail=f"Repository limit reached ({MAX_REPOSITORIES_PER_USER})")
        try:
            cursor = db.execute(
                "INSERT INTO repositories(owner_id,name,description,visibility,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                (user["id"], name, body.description.strip(), body.visibility, now, now),
            )
            repository_id = cursor.lastrowid
            db.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Repository name already exists") from exc
        path = _repo_path(repository_id)
        try:
            path.mkdir(parents=True, exist_ok=False)
            repo = Repo.init(path, initial_branch="main")
            filename = "README.md" if body.initialize_readme else ".gitkeep"
            content = f"# {name}\n\n{body.description.strip()}\n" if body.initialize_readme else ""
            (path / filename).write_text(content, encoding="utf-8")
            with repo.config_writer() as config:
                config.set_value("user", "name", user["name"] or user["email"])
                config.set_value("user", "email", user["email"])
            repo.index.add([filename])
            repo.index.commit("Initial commit")
        except Exception:
            shutil.rmtree(path, ignore_errors=True)
            db.execute("DELETE FROM repositories WHERE id = ?", (repository_id,))
            db.commit()
            raise
        return _response(_access(db, repository_id, user["id"]))


@router.get("", response_model=list[RepositoryResponse])
def list_repositories(user: sqlite3.Row = Depends(_current_user)) -> list[RepositoryResponse]:
    with _db() as db:
        rows = db.execute(
            """SELECT r.*, u.name AS owner_name,
                CASE WHEN r.owner_id = ? THEN 'owner' ELSE c.role END AS role
               FROM repositories r JOIN users u ON u.id=r.owner_id
               LEFT JOIN repository_collaborators c ON c.repository_id=r.id AND c.user_id=?
               WHERE r.owner_id=? OR c.user_id=? OR r.visibility='public'
               ORDER BY r.updated_at DESC""",
            (user["id"], user["id"], user["id"], user["id"]),
        ).fetchall()
        return [_response(row) for row in rows]


@router.get("/{repository_id}", response_model=RepositoryResponse)
def get_repository(repository_id: int, user: sqlite3.Row = Depends(_current_user)) -> RepositoryResponse:
    with _db() as db:
        return _response(_access(db, repository_id, user["id"]))


@router.delete("/{repository_id}", status_code=204)
def delete_repository(repository_id: int, response: Response, user: sqlite3.Row = Depends(_current_user)) -> Response:
    with _repo_lock(repository_id), _db() as db:
        row = _access(db, repository_id, user["id"])
        _require_owner(row)
        db.execute("DELETE FROM repositories WHERE id = ?", (repository_id,))
        db.commit()
        shutil.rmtree(_repo_path(repository_id), ignore_errors=True)
    response.status_code = 204
    return response


@router.get("/{repository_id}/tree")
def list_tree(repository_id: int, branch: str = Query("main"), user: sqlite3.Row = Depends(_current_user)) -> list[dict]:
    with _repo_lock(repository_id), _db() as db:
        _access(db, repository_id, user["id"])
        repo = _open(repository_id)
        _checkout(repo, branch)
        root = _repo_path(repository_id)
        result = []
        for item in sorted(root.rglob("*")):
            if ".git" in item.parts or item == root:
                continue
            result.append({"path": item.relative_to(root).as_posix(), "type": "directory" if item.is_dir() else "file", "size": item.stat().st_size if item.is_file() else 0})
        return result


@router.get("/{repository_id}/files")
def read_file(repository_id: int, path: str, branch: str = Query("main"), user: sqlite3.Row = Depends(_current_user)) -> dict:
    relative = _safe_relative(path)
    with _repo_lock(repository_id), _db() as db:
        _access(db, repository_id, user["id"])
        repo = _open(repository_id)
        _checkout(repo, branch)
        target = _repo_path(repository_id) / relative
        if not target.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=415, detail="Binary files cannot be opened in the editor") from exc
        return {"path": relative.as_posix(), "content": content, "branch": branch, "size": target.stat().st_size}


@router.put("/{repository_id}/files")
def write_file(repository_id: int, body: FileWriteRequest, user: sqlite3.Row = Depends(_current_user)) -> dict:
    relative = _safe_relative(body.path)
    with _repo_lock(repository_id), _db() as db:
        row = _access(db, repository_id, user["id"])
        _require_write(row)
        repo = _open(repository_id)
        _checkout(repo, body.branch)
        target = _repo_path(repository_id) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body.content, encoding="utf-8")
        if _size(_repo_path(repository_id)) > MAX_REPOSITORY_BYTES:
            repo.git.reset("--hard")
            repo.git.clean("-fd")
            raise HTTPException(status_code=413, detail="Repository size limit exceeded")
        commit = _commit(repo, body.commit_message, user)
        db.execute("UPDATE repositories SET updated_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), repository_id))
        db.commit()
        return {"path": relative.as_posix(), "branch": body.branch, "commit": commit}


@router.post("/{repository_id}/move")
def move_file(repository_id: int, body: FileMoveRequest, user: sqlite3.Row = Depends(_current_user)) -> dict:
    source = _safe_relative(body.source_path)
    destination = _safe_relative(body.destination_path)
    with _repo_lock(repository_id), _db() as db:
        row = _access(db, repository_id, user["id"])
        _require_write(row)
        repo = _open(repository_id)
        _checkout(repo, body.branch)
        root = _repo_path(repository_id)
        if not (root / source).exists():
            raise HTTPException(status_code=404, detail="Source not found")
        (root / destination).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(root / source, root / destination)
        commit = _commit(repo, body.commit_message, user)
        return {"path": destination.as_posix(), "branch": body.branch, "commit": commit}


@router.delete("/{repository_id}/files")
def delete_file(repository_id: int, body: FileDeleteRequest, user: sqlite3.Row = Depends(_current_user)) -> dict:
    relative = _safe_relative(body.path)
    with _repo_lock(repository_id), _db() as db:
        row = _access(db, repository_id, user["id"])
        _require_write(row)
        repo = _open(repository_id)
        _checkout(repo, body.branch)
        target = _repo_path(repository_id) / relative
        if not target.exists():
            raise HTTPException(status_code=404, detail="File or folder not found")
        shutil.rmtree(target) if target.is_dir() else target.unlink()
        commit = _commit(repo, body.commit_message, user)
        return {"path": relative.as_posix(), "branch": body.branch, "commit": commit}


@router.get("/{repository_id}/branches")
def list_branches(repository_id: int, user: sqlite3.Row = Depends(_current_user)) -> list[str]:
    with _repo_lock(repository_id), _db() as db:
        _access(db, repository_id, user["id"])
        return [head.name for head in _open(repository_id).heads]


@router.post("/{repository_id}/branches", status_code=201)
def create_branch(repository_id: int, body: BranchCreateRequest, user: sqlite3.Row = Depends(_current_user)) -> dict:
    name = _safe_branch(body.name)
    source = _safe_branch(body.source_branch)
    with _repo_lock(repository_id), _db() as db:
        row = _access(db, repository_id, user["id"])
        _require_write(row)
        repo = _open(repository_id)
        if name in [head.name for head in repo.heads]:
            raise HTTPException(status_code=409, detail="Branch already exists")
        if source not in [head.name for head in repo.heads]:
            raise HTTPException(status_code=404, detail="Source branch not found")
        repo.create_head(name, repo.heads[source].commit)
        return {"name": name, "source_branch": source}


@router.get("/{repository_id}/commits")
def list_commits(repository_id: int, branch: str = Query("main"), limit: int = Query(50, ge=1, le=100), user: sqlite3.Row = Depends(_current_user)) -> list[dict]:
    with _repo_lock(repository_id), _db() as db:
        _access(db, repository_id, user["id"])
        repo = _open(repository_id)
        _checkout(repo, branch)
        return [{"sha": commit.hexsha, "message": commit.message.strip(), "author": commit.author.name, "email": commit.author.email, "created_at": datetime.fromtimestamp(commit.committed_date, timezone.utc).isoformat()} for commit in list(repo.iter_commits(branch, max_count=limit))]


@router.post("/{repository_id}/collaborators")
def add_collaborator(repository_id: int, body: CollaboratorRequest, user: sqlite3.Row = Depends(_current_user)) -> dict:
    email = body.email.strip().lower()
    with _db() as db:
        row = _access(db, repository_id, user["id"])
        _require_owner(row)
        collaborator = db.execute("SELECT id, name, email FROM users WHERE email=?", (email,)).fetchone()
        if not collaborator:
            raise HTTPException(status_code=404, detail="User not found")
        if collaborator["id"] == row["owner_id"]:
            raise HTTPException(status_code=409, detail="Owner is already a collaborator")
        db.execute("INSERT INTO repository_collaborators(repository_id,user_id,role,created_at) VALUES (?,?,?,?) ON CONFLICT(repository_id,user_id) DO UPDATE SET role=excluded.role", (repository_id, collaborator["id"], body.role, datetime.now(timezone.utc).isoformat()))
        db.commit()
        return {"user_id": collaborator["id"], "name": collaborator["name"], "email": collaborator["email"], "role": body.role}
