"""GitHub OAuth connection, repository import, pull, and push support."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from git import Repo
from git.exc import GitCommandError
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import DB_PATH, get_user_from_session
from amoscloud_ai.api.routes.repositories import (
    MAX_REPOSITORIES_PER_USER,
    REPOSITORY_ROOT,
    _NAME_RE,
)

router = APIRouter(prefix="/github", tags=["github-repositories"])
OAUTH_STATE_COOKIE = "amos_github_repository_state"


class GitHubImportRequest(BaseModel):
    full_name: str = Field(..., pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitHubSyncRequest(BaseModel):
    branch: str | None = Field(default=None, max_length=200)
    commit_message: str = Field(default="Sync changes from Amosclaud", min_length=1, max_length=200)


class GitHubIssueCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    body: str = Field(default="", max_length=60_000)
    labels: list[str] = Field(default_factory=list, max_length=20)


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS github_connections (
            user_id INTEGER PRIMARY KEY,
            github_id TEXT NOT NULL UNIQUE,
            github_login TEXT NOT NULL,
            access_token_ciphertext TEXT NOT NULL,
            scopes TEXT NOT NULL DEFAULT '',
            connected_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    columns = {row[1] for row in db.execute("PRAGMA table_info(repositories)").fetchall()}
    additions = {
        "github_full_name": "TEXT",
        "github_html_url": "TEXT",
        "github_default_branch": "TEXT",
        "github_last_sync_at": "TEXT",
    }
    for name, sql_type in additions.items():
        if name not in columns:
            db.execute(f"ALTER TABLE repositories ADD COLUMN {name} {sql_type}")
    db.commit()
    return db


def _current_user(amos_session: str | None = Cookie(default=None)) -> sqlite3.Row:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _fernet() -> Fernet:
    secret = os.getenv("GITHUB_TOKEN_ENCRYPTION_KEY")
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="GitHub token encryption is not configured",
        )
    try:
        if len(secret) == 44:
            return Fernet(secret.encode())
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        return Fernet(key)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Invalid GitHub token encryption key") from exc


def _encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def _decrypt_token(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise HTTPException(status_code=503, detail="Stored GitHub authorization is unreadable; reconnect GitHub") from exc


def _connection(db: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    row = db.execute("SELECT * FROM github_connections WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=409, detail="Connect GitHub before accessing repositories")
    return row


def _authenticated_clone_url(full_name: str, token: str) -> str:
    return f"https://x-access-token:{quote(token, safe='')}@github.com/{full_name}.git"


def _public_remote_url(full_name: str) -> str:
    return f"https://github.com/{full_name}.git"


@router.get("/connect")
def connect_github(request: Request, user: sqlite3.Row = Depends(_current_user)) -> RedirectResponse:
    del user
    client_id = os.getenv("GITHUB_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=503, detail="GitHub integration is not configured")
    state = secrets.token_urlsafe(32)
    callback = os.getenv("GITHUB_REPOSITORY_CALLBACK_URL") or str(request.url_for("github_repository_callback"))
    authorize_url = "https://github.com/login/oauth/authorize?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": callback,
            "scope": "read:user user:email repo",
            "state": state,
        }
    )
    response = RedirectResponse(authorize_url)
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        secure=os.getenv("AUTH_COOKIE_SECURE", "true").lower() == "true",
        samesite="lax",
        path="/",
    )
    return response


@router.get("/callback", name="github_repository_callback")
async def github_repository_callback(
    code: str,
    state: str,
    request: Request,
    amos_github_repository_state: str | None = Cookie(default=None),
    user: sqlite3.Row = Depends(_current_user),
) -> RedirectResponse:
    if not amos_github_repository_state or not hmac.compare_digest(state, amos_github_repository_state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    client_id = os.getenv("GITHUB_CLIENT_ID")
    client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=503, detail="GitHub integration is not configured")
    callback = os.getenv("GITHUB_REPOSITORY_CALLBACK_URL") or str(request.url_for("github_repository_callback"))
    async with httpx.AsyncClient(timeout=20) as client:
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": callback,
            },
        )
        token_payload = token_response.json()
        access_token = token_payload.get("access_token")
        if not access_token:
            raise HTTPException(status_code=401, detail="GitHub connection failed")
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        profile_response = await client.get("https://api.github.com/user", headers=headers)
        if profile_response.status_code >= 400:
            raise HTTPException(status_code=401, detail="Unable to read GitHub profile")
        profile = profile_response.json()
    github_id = str(profile.get("id") or "")
    github_login = str(profile.get("login") or "")
    if not github_id or not github_login:
        raise HTTPException(status_code=400, detail="GitHub account information is incomplete")
    now = datetime.now(timezone.utc).isoformat()
    with _db() as db:
        conflict = db.execute(
            "SELECT user_id FROM github_connections WHERE github_id=? AND user_id!=?",
            (github_id, user["id"]),
        ).fetchone()
        if conflict:
            raise HTTPException(status_code=409, detail="This GitHub account is linked to another Amosclaud user")
        db.execute(
            """
            INSERT INTO github_connections(user_id,github_id,github_login,access_token_ciphertext,scopes,connected_at,updated_at)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                github_id=excluded.github_id,
                github_login=excluded.github_login,
                access_token_ciphertext=excluded.access_token_ciphertext,
                scopes=excluded.scopes,
                updated_at=excluded.updated_at
            """,
            (
                user["id"],
                github_id,
                github_login,
                _encrypt_token(access_token),
                str(token_payload.get("scope") or ""),
                now,
                now,
            ),
        )
        db.execute(
            "UPDATE users SET github_id=?, provider='password+github' WHERE id=?",
            (github_id, user["id"]),
        )
        db.commit()
    response = RedirectResponse("/repositories?github=connected", status_code=302)
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    return response


@router.get("/status")
def github_status(user: sqlite3.Row = Depends(_current_user)) -> dict:
    with _db() as db:
        row = db.execute(
            "SELECT github_login,scopes,connected_at,updated_at FROM github_connections WHERE user_id=?",
            (user["id"],),
        ).fetchone()
    return {"connected": bool(row), "connection": dict(row) if row else None}


@router.delete("/connection", status_code=204)
def disconnect_github(user: sqlite3.Row = Depends(_current_user)) -> None:
    with _db() as db:
        db.execute("DELETE FROM github_connections WHERE user_id=?", (user["id"],))
        db.execute("UPDATE users SET github_id=NULL, provider='password' WHERE id=?", (user["id"],))
        db.commit()


@router.get("/repositories")
async def list_github_repositories(user: sqlite3.Row = Depends(_current_user)) -> list[dict]:
    with _db() as db:
        connection = _connection(db, user["id"])
        token = _decrypt_token(connection["access_token_ciphertext"])
        imported = {
            row["github_full_name"]: row["id"]
            for row in db.execute(
                "SELECT id,github_full_name FROM repositories WHERE owner_id=? AND github_full_name IS NOT NULL",
                (user["id"],),
            ).fetchall()
        }
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    results: list[dict] = []
    async with httpx.AsyncClient(timeout=20) as client:
        for page in range(1, 11):
            response = await client.get(
                "https://api.github.com/user/repos",
                headers=headers,
                params={"per_page": 100, "page": page, "sort": "updated", "affiliation": "owner,collaborator,organization_member"},
            )
            if response.status_code in {401, 403}:
                raise HTTPException(status_code=401, detail="GitHub authorization expired; reconnect GitHub")
            if response.status_code >= 400:
                raise HTTPException(status_code=502, detail="GitHub repository listing failed")
            items = response.json()
            for item in items:
                full_name = item.get("full_name")
                if not full_name:
                    continue
                permissions = item.get("permissions") or {}
                results.append(
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "full_name": full_name,
                        "description": item.get("description") or "",
                        "private": bool(item.get("private")),
                        "default_branch": item.get("default_branch") or "main",
                        "html_url": item.get("html_url"),
                        "updated_at": item.get("updated_at"),
                        "can_push": bool(permissions.get("push") or permissions.get("admin") or permissions.get("maintain")),
                        "imported_repository_id": imported.get(full_name),
                    }
                )
            if len(items) < 100:
                break
    return results


@router.post("/repositories/import", status_code=201)
def import_github_repository(body: GitHubImportRequest, user: sqlite3.Row = Depends(_current_user)) -> dict:
    full_name = body.full_name.strip()
    with _db() as db:
        connection = _connection(db, user["id"])
        if db.execute(
            "SELECT id FROM repositories WHERE owner_id=? AND github_full_name=?",
            (user["id"], full_name),
        ).fetchone():
            raise HTTPException(status_code=409, detail="This GitHub repository is already imported")
        count = db.execute("SELECT COUNT(*) FROM repositories WHERE owner_id=?", (user["id"],)).fetchone()[0]
        if count >= MAX_REPOSITORIES_PER_USER:
            raise HTTPException(status_code=403, detail=f"Repository limit reached ({MAX_REPOSITORIES_PER_USER})")
        token = _decrypt_token(connection["access_token_ciphertext"])

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(timeout=20) as client:
        response = client.get(f"https://api.github.com/repos/{full_name}", headers=headers)
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="GitHub repository not found or not accessible")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Unable to read GitHub repository")
    metadata = response.json()
    name = str(metadata.get("name") or full_name.split("/", 1)[1])
    if not _NAME_RE.fullmatch(name):
        raise HTTPException(status_code=422, detail="GitHub repository name is not supported by Amosclaud")
    now = datetime.now(timezone.utc).isoformat()
    with _db() as db:
        existing_name = db.execute(
            "SELECT 1 FROM repositories WHERE owner_id=? AND name=? COLLATE NOCASE",
            (user["id"], name),
        ).fetchone()
        if existing_name:
            name = f"{name}-github"
        cursor = db.execute(
            """
            INSERT INTO repositories(
                owner_id,name,description,visibility,default_branch,created_at,updated_at,
                github_full_name,github_html_url,github_default_branch,github_last_sync_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                user["id"],
                name,
                str(metadata.get("description") or ""),
                "private" if metadata.get("private") else "public",
                str(metadata.get("default_branch") or "main"),
                now,
                now,
                full_name,
                str(metadata.get("html_url") or ""),
                str(metadata.get("default_branch") or "main"),
                now,
            ),
        )
        repository_id = cursor.lastrowid
        db.commit()
    path = REPOSITORY_ROOT / str(repository_id)
    try:
        REPOSITORY_ROOT.mkdir(parents=True, exist_ok=True)
        Repo.clone_from(_authenticated_clone_url(full_name, token), path)
        repo = Repo(path)
        repo.remote("origin").set_url(_public_remote_url(full_name))
    except Exception as exc:
        shutil.rmtree(path, ignore_errors=True)
        with _db() as db:
            db.execute("DELETE FROM repositories WHERE id=?", (repository_id,))
            db.commit()
        raise HTTPException(status_code=502, detail="GitHub repository clone failed") from exc
    return {
        "id": repository_id,
        "name": name,
        "github_full_name": full_name,
        "default_branch": metadata.get("default_branch") or "main",
        "workspace_url": f"/workspace/{repository_id}",
    }


def _owned_github_repository(db: sqlite3.Connection, repository_id: int, user_id: int) -> sqlite3.Row:
    row = db.execute(
        "SELECT * FROM repositories WHERE id=? AND owner_id=? AND github_full_name IS NOT NULL",
        (repository_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Imported GitHub repository not found")
    return row


@router.post("/repositories/{repository_id}/pull")
def pull_github_repository(
    repository_id: int,
    body: GitHubSyncRequest,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    with _db() as db:
        row = _owned_github_repository(db, repository_id, user["id"])
        connection = _connection(db, user["id"])
        token = _decrypt_token(connection["access_token_ciphertext"])
    repo = Repo(REPOSITORY_ROOT / str(repository_id))
    branch = body.branch or row["github_default_branch"] or row["default_branch"] or "main"
    remote = repo.remote("origin")
    original_url = remote.url
    try:
        remote.set_url(_authenticated_clone_url(row["github_full_name"], token))
        repo.git.checkout(branch)
        repo.git.pull("--ff-only", "origin", branch)
    except GitCommandError as exc:
        raise HTTPException(status_code=409, detail="Pull could not be completed with a fast-forward merge") from exc
    finally:
        remote.set_url(original_url or _public_remote_url(row["github_full_name"]))
    now = datetime.now(timezone.utc).isoformat()
    with _db() as db:
        db.execute("UPDATE repositories SET updated_at=?,github_last_sync_at=? WHERE id=?", (now, now, repository_id))
        db.commit()
    return {"repository_id": repository_id, "branch": branch, "commit": repo.head.commit.hexsha, "synced_at": now}


@router.post("/repositories/{repository_id}/push")
def push_github_repository(
    repository_id: int,
    body: GitHubSyncRequest,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    with _db() as db:
        row = _owned_github_repository(db, repository_id, user["id"])
        connection = _connection(db, user["id"])
        token = _decrypt_token(connection["access_token_ciphertext"])
    repo = Repo(REPOSITORY_ROOT / str(repository_id))
    branch = body.branch or (repo.active_branch.name if not repo.head.is_detached else row["github_default_branch"] or "main")
    if repo.is_dirty(untracked_files=True):
        repo.git.add(A=True)
        with repo.config_writer() as config:
            config.set_value("user", "name", user["name"] or user["email"])
            config.set_value("user", "email", user["email"])
        repo.index.commit(body.commit_message.strip())
    remote = repo.remote("origin")
    original_url = remote.url
    try:
        remote.set_url(_authenticated_clone_url(row["github_full_name"], token))
        repo.git.push("origin", f"HEAD:{branch}")
    except GitCommandError as exc:
        raise HTTPException(status_code=409, detail="GitHub rejected the push; pull remote changes first or check repository permissions") from exc
    finally:
        remote.set_url(original_url or _public_remote_url(row["github_full_name"]))
    now = datetime.now(timezone.utc).isoformat()
    with _db() as db:
        db.execute("UPDATE repositories SET updated_at=?,github_last_sync_at=? WHERE id=?", (now, now, repository_id))
        db.commit()
    return {"repository_id": repository_id, "branch": branch, "commit": repo.head.commit.hexsha, "synced_at": now}

@router.post("/repositories/{repository_id}/issues", status_code=201)
async def create_github_issue(
    repository_id: int,
    body: GitHubIssueCreateRequest,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    """Create a real issue only in the signed-in user's imported GitHub repository."""
    with _db() as db:
        repository = _owned_github_repository(db, repository_id, int(user["id"]))
        connection = _connection(db, int(user["id"]))
        token = _decrypt_token(connection["access_token_ciphertext"])

    labels = []
    for label in body.labels:
        value = " ".join(str(label).split())
        if not value or len(value) > 50:
            raise HTTPException(status_code=422, detail="Issue labels must be 1-50 characters")
        labels.append(value)

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"https://api.github.com/repos/{repository['github_full_name']}/issues",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "title": body.title.strip(),
                "body": body.body,
                "labels": labels,
            },
        )
    if response.status_code in {401, 403}:
        raise HTTPException(
            status_code=403,
            detail="The connected GitHub account cannot create issues in this repository",
        )
    if response.status_code == 404:
        raise HTTPException(
            status_code=404,
            detail="GitHub repository not found or Issues are disabled",
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="GitHub issue creation failed")

    issue = response.json()
    return {
        "repository_id": repository_id,
        "github_full_name": repository["github_full_name"],
        "number": issue["number"],
        "title": issue["title"],
        "state": issue["state"],
        "html_url": issue["html_url"],
        "created_at": issue["created_at"],
    }

