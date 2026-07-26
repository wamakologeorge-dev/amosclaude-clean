"""Native repository hosting for Amosclaud platform users."""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response
from git import Repo
from git.exc import InvalidGitRepositoryError
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import DB_PATH, get_user_from_session
from amoscloud_ai.markdown_service import render_markdown_document

router = APIRouter(prefix="/repositories", tags=["repositories"])

REPOSITORY_ROOT = Path(os.getenv("REPOSITORY_STORAGE_PATH", "data/repositories"))
MAX_REPOSITORIES_PER_USER = int(os.getenv("MAX_REPOSITORIES_PER_USER", "10"))
MAX_REPOSITORY_BYTES = int(os.getenv("MAX_REPOSITORY_BYTES", str(500 * 1024 * 1024)))
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_LOCKS: dict[int, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkd"}
_INLINE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".ico": "image/x-icon",
}
_LANGUAGE_BY_SUFFIX = {
    ".py": "Python",
    ".pyi": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "Sass",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".c": "C",
    ".h": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".php": "PHP",
    ".rb": "Ruby",
    ".swift": "Swift",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".sql": "SQL",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".amcl": "Amosclaud Language",
}


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


class VisibilityUpdateRequest(BaseModel):
    visibility: Literal["private", "public"]


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


def _starter_files(name: str, description: str, initialize_readme: bool) -> dict[str, str]:
    """Return the standard structure for every Amosclaud developer repository."""
    files = {
        ".Amosclaud-workflow/workflow.yml": (
            "name: Amosclaud Workflow\n"
            "version: 1\n"
            "entry: Src/app/example.tsx\n"
            "steps:\n"
            "  - build\n"
            "  - test\n"
            "  - review\n"
        ),
        "Src/app/example.tsx": (
            "export default function Example() {\n"
            "  return (\n"
            "    <main>\n"
            f"      <h1>{name}</h1>\n"
            "      <p>Built with Amosclaud.</p>\n"
            "    </main>\n"
            "  );\n"
            "}\n"
        ),
    }
    if initialize_readme:
        files["README.md"] = f"# {name}\n\n{description}\n"
    return files


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
            starter_files = _starter_files(name, body.description.strip(), body.initialize_readme)
            for relative_path, content in starter_files.items():
                target = path / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            with repo.config_writer() as config:
                config.set_value("user", "name", user["name"] or user["email"])
                config.set_value("user", "email", user["email"])
            repo.index.add(list(starter_files))
            repo.index.commit("Initialize Amosclaud developer repository")
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


@router.patch("/{repository_id}/visibility", response_model=RepositoryResponse)
def update_visibility(
    repository_id: int,
    body: VisibilityUpdateRequest,
    user: sqlite3.Row = Depends(_current_user),
) -> RepositoryResponse:
    """Publish or unpublish a repository. Owner only, enforced server-side.

    ``_access`` already hides private repositories from users who cannot see
    them (404), and ``_require_owner`` rejects collaborators and readers of
    public repositories (403). The client is never trusted: the role is
    recomputed from the database on every call.
    """
    with _db() as db:
        row = _access(db, repository_id, user["id"])
        _require_owner(row)
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "UPDATE repositories SET visibility = ?, updated_at = ? WHERE id = ?",
            (body.visibility, now, repository_id),
        )
        db.commit()
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




def _repository_files(root: Path) -> list[Path]:
    """Return working-tree files without exposing Git's private storage."""
    base_root = REPOSITORY_ROOT.resolve()
    safe_root = root.resolve()
    try:
        safe_root.relative_to(base_root)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid repository path") from exc

    return [
        item
        for item in safe_root.rglob("*")
        if item.is_file() and ".git" not in item.relative_to(safe_root).parts
    ]


def _is_markdown_path(path: Path) -> bool:
    return path.suffix.casefold() in _MARKDOWN_SUFFIXES or path.name.casefold() in {
        "readme",
        "license",
        "contributing",
        "security",
        "code_of_conduct",
    }


def _language_summary(root: Path, files: list[Path]) -> list[dict]:
    measured: Counter[str] = Counter()
    for item in files:
        language = _LANGUAGE_BY_SUFFIX.get(item.suffix.casefold())
        if not language and item.name.casefold() in {"dockerfile", "containerfile"}:
            language = "Dockerfile"
        if language:
            measured[language] += max(item.stat().st_size, 1)
    total = sum(measured.values())
    if not total:
        return []
    return [
        {
            "name": language,
            "bytes": size,
            "percentage": round((size / total) * 100, 2),
        }
        for language, size in measured.most_common()
    ]


def _root_file_lookup(root: Path, files: list[Path]) -> dict[str, str]:
    return {
        item.name.casefold(): item.relative_to(root).as_posix()
        for item in files
        if item.parent == root
    }


def _first_root_file(lookup: dict[str, str], *names: str) -> str | None:
    for name in names:
        if name.casefold() in lookup:
            return lookup[name.casefold()]
    return None


@router.get("/{repository_id}/overview")
def repository_overview(
    repository_id: int,
    branch: str = Query("main"),
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    """Return real repository facts for the workspace details sidebar."""
    with _repo_lock(repository_id), _db() as db:
        _access(db, repository_id, user["id"])
        repo = _open(repository_id)
        _checkout(repo, branch)
        root = _repo_path(repository_id)
        files = _repository_files(root)
        lookup = _root_file_lookup(root, files)
        license_path = _first_root_file(
            lookup,
            "LICENSE",
            "LICENSE.md",
            "LICENSE.txt",
            "COPYING",
            "COPYING.md",
        )
        return {
            "branch": branch,
            "branch_count": len(repo.heads),
            "tag_count": len(repo.tags),
            "commit_count": sum(1 for _ in repo.iter_commits(branch)),
            "file_count": len(files),
            "repository_size": sum(item.stat().st_size for item in files),
            "languages": _language_summary(root, files),
            "license_label": "License" if license_path else None,
            "features": {
                "license": license_path,
                "code_of_conduct": _first_root_file(
                    lookup,
                    "CODE_OF_CONDUCT.md",
                    "CODE-OF-CONDUCT.md",
                    "CODE_OF_CONDUCT.txt",
                ),
                "contributing": _first_root_file(
                    lookup,
                    "CONTRIBUTING.md",
                    "CONTRIBUTING.txt",
                ),
                "security_policy": _first_root_file(
                    lookup,
                    "SECURITY.md",
                    "SECURITY.txt",
                ),
            },
        }


@router.get("/{repository_id}/markdown")
def render_repository_markdown(
    repository_id: int,
    path: str,
    branch: str = Query("main"),
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    """Render one repository Markdown file through Amosclaud's safe service."""
    relative = _safe_relative(path)
    if not _is_markdown_path(relative):
        raise HTTPException(status_code=415, detail="This file is not supported Markdown")
    with _repo_lock(repository_id), _db() as db:
        _access(db, repository_id, user["id"])
        repo = _open(repository_id)
        _checkout(repo, branch)
        repo_root = _repo_path(repository_id).resolve()
        target = (repo_root / relative).resolve()
        try:
            target.relative_to(repo_root)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid file path") from exc
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Markdown file not found")
        try:
            source = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=415, detail="Markdown must be UTF-8 text") from exc
        try:
            document = render_markdown_document(
                source,
                repository_id=repository_id,
                branch=branch,
                source_path=relative.as_posix(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        return {
            "path": relative.as_posix(),
            "branch": branch,
            "html": document.html,
            "outline": list(document.outline),
            "source_sha256": document.source_sha256,
        }


@router.get("/{repository_id}/raw")
def read_repository_media(
    repository_id: int,
    path: str,
    branch: str = Query("main"),
    user: sqlite3.Row = Depends(_current_user),
) -> Response:
    """Serve only safe inline image formats referenced by repository Markdown."""
    relative = _safe_relative(path)
    media_type = _INLINE_MEDIA_TYPES.get(relative.suffix.casefold())
    if not media_type:
        raise HTTPException(status_code=415, detail="Inline media type is not allowed")
    with _repo_lock(repository_id), _db() as db:
        _access(db, repository_id, user["id"])
        repo = _open(repository_id)
        _checkout(repo, branch)
        repository_root = _repo_path(repository_id).resolve()
        target = (repository_root / relative).resolve(strict=False)
        try:
            target.relative_to(repository_root)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid file path") from exc
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Media file not found")
        if target.stat().st_size > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Inline media exceeds the 10 MB limit")
        return Response(
            content=target.read_bytes(),
            media_type=media_type,
            headers={
                "Cache-Control": "private, max-age=300",
                "Content-Security-Policy": "default-src 'none'; sandbox",
                "X-Content-Type-Options": "nosniff",
            },
        )


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
