"""GitHub account connection and real repository import/synchronization."""

from __future__ import annotations

import base64
import hashlib
import os
import re
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
    REPOSITORY_ROOT,
    _NAME_RE,
    _repo_lock,
    _safe_branch,
)
from amoscloud_ai.db_migrations import ensure_github_repository_schema
from amoscloud_ai.github_git_auth import authenticated_git, git_auth_environment

router = APIRouter(prefix="/github", tags=["github-repositories"])
OAUTH_STATE_COOKIE = "amos_github_oauth_state"
_GITHUB_FULL_NAME = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$"
)


class GitHubImportRequest(BaseModel):
    full_name: str = Field(..., min_length=3, max_length=200)


class GitHubSyncRequest(BaseModel):
    branch: str | None = Field(default=None, max_length=200)
    commit_message: str = Field(
        default="Update from Amosclaud workspace",
        min_length=1,
        max_length=200,
    )


class GitHubIssueCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(default="", max_length=60_000)
    labels: list[str] = Field(default_factory=list, max_length=20)


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute(
        """CREATE TABLE IF NOT EXISTS github_connections (
            user_id INTEGER PRIMARY KEY,
            github_user_id INTEGER NOT NULL,
            github_login TEXT NOT NULL,
            avatar_url TEXT,
            access_token_ciphertext TEXT NOT NULL,
            scopes TEXT NOT NULL DEFAULT '',
            connected_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS repositories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            name TEXT NOT NULL COLLATE NOCASE,
            description TEXT NOT NULL DEFAULT '',
            visibility TEXT NOT NULL DEFAULT 'private',
            default_branch TEXT NOT NULL DEFAULT 'main',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(owner_id,name),
            FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE
        )"""
    )
    ensure_github_repository_schema(db)
    db.commit()
    return db


def _fernet() -> Fernet:
    configured = os.getenv("GITHUB_TOKEN_ENCRYPTION_KEY", "").strip()
    if not configured:
        if os.getenv("ENVIRONMENT", "development").lower() in {"production", "prod"}:
            raise RuntimeError("GITHUB_TOKEN_ENCRYPTION_KEY is required in production")
        configured = "amosclaud-local-github-token-key"
    key = base64.urlsafe_b64encode(hashlib.sha256(configured.encode()).digest())
    return Fernet(key)


def _encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def _decrypt_token(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise HTTPException(
            status_code=503,
            detail="Stored GitHub authorization can no longer be decrypted; reconnect GitHub",
        ) from exc


def _current_user(amos_session: str | None = Cookie(default=None)) -> sqlite3.Row:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to connect GitHub")
    return user


def _connection(db: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    row = db.execute(
        "SELECT * FROM github_connections WHERE user_id=?",
        (user_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=409, detail="Connect GitHub first")
    return row


def _public_remote_url(full_name: str) -> str:
    return f"https://github.com/{full_name}.git"


def _authenticated_clone_url(full_name: str, token: str) -> str:
    """Compatibility helper that never embeds the supplied credential."""

    del token
    return _public_remote_url(full_name)


def _clean_full_name(value: str) -> str:
    full_name = value.strip()
    if not _GITHUB_FULL_NAME.fullmatch(full_name):
        raise HTTPException(status_code=422, detail="Use a valid owner/repository name")
    return full_name


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _json_object(response: httpx.Response, fallback: str) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=fallback) from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail=fallback)
    return payload


@router.get("/connect")
def connect_github(
    request: Request,
    user: sqlite3.Row = Depends(_current_user),
) -> RedirectResponse:
    del user
    client_id = os.getenv("GITHUB_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=503, detail="GitHub integration is not configured")
    state = secrets.token_urlsafe(32)
    callback = os.getenv("GITHUB_REPOSITORY_CALLBACK_URL") or str(
        request.url_for("github_repository_callback")
    )
    authorize_url = "https://github.com/login/oauth/authorize?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": callback,
            "scope": "read:user user:email repo workflow",
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
def github_repository_callback(
    request: Request,
    code: str,
    state: str,
    amos_session: str | None = Cookie(default=None),
    oauth_state: str | None = Cookie(default=None, alias=OAUTH_STATE_COOKIE),
) -> RedirectResponse:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in before connecting GitHub")
    if not oauth_state or not secrets.compare_digest(state, oauth_state):
        raise HTTPException(status_code=400, detail="GitHub authorization state is invalid")
    client_id = os.getenv("GITHUB_CLIENT_ID")
    client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=503, detail="GitHub integration is not configured")
    callback = os.getenv("GITHUB_REPOSITORY_CALLBACK_URL") or str(
        request.url_for("github_repository_callback")
    )
    with httpx.Client(timeout=20) as client:
        token_response = client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": callback,
            },
        )
        token_payload = _json_object(
            token_response,
            "GitHub returned an invalid authorization response",
        )
        access_token = str(token_payload.get("access_token") or "")
        if token_response.status_code >= 400 or not access_token:
            raise HTTPException(status_code=502, detail="GitHub authorization failed")
        profile_response = client.get(
            "https://api.github.com/user",
            headers=_github_headers(access_token),
        )
    if profile_response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Unable to read the GitHub profile")
    profile = _json_object(profile_response, "GitHub returned an invalid profile")
    scopes = token_response.headers.get("X-OAuth-Scopes", "")
    now = datetime.now(timezone.utc).isoformat()
    with _db() as db:
        db.execute(
            """INSERT INTO github_connections
               (user_id,github_user_id,github_login,avatar_url,access_token_ciphertext,
                scopes,connected_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 github_user_id=excluded.github_user_id,
                 github_login=excluded.github_login,
                 avatar_url=excluded.avatar_url,
                 access_token_ciphertext=excluded.access_token_ciphertext,
                 scopes=excluded.scopes,
                 updated_at=excluded.updated_at""",
            (
                user["id"],
                int(profile["id"]),
                str(profile["login"]),
                str(profile.get("avatar_url") or ""),
                _encrypt_token(access_token),
                scopes,
                now,
                now,
            ),
        )
        db.commit()
    response = RedirectResponse("/repositories?github=connected", status_code=302)
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    return response


@router.get("/status")
def github_status(user: sqlite3.Row = Depends(_current_user)) -> dict:
    with _db() as db:
        row = db.execute(
            """SELECT github_login,avatar_url,scopes,connected_at,updated_at
               FROM github_connections WHERE user_id=?""",
            (user["id"],),
        ).fetchone()
    if not row:
        return {"connected": False}
    return {"connected": True, **dict(row)}


@router.delete("/connection", status_code=204)
def disconnect_github(user: sqlite3.Row = Depends(_current_user)) -> None:
    with _db() as db:
        db.execute("DELETE FROM github_connections WHERE user_id=?", (user["id"],))
        db.commit()


@router.get("/repositories")
def list_github_repositories(user: sqlite3.Row = Depends(_current_user)) -> dict:
    with _db() as db:
        connection = _connection(db, user["id"])
        token = _decrypt_token(connection["access_token_ciphertext"])
    repositories: list[dict] = []
    with httpx.Client(timeout=20) as client:
        for page in range(1, 11):
            response = client.get(
                "https://api.github.com/user/repos",
                headers=_github_headers(token),
                params={
                    "sort": "updated",
                    "direction": "desc",
                    "per_page": 100,
                    "page": page,
                    "affiliation": "owner,collaborator,organization_member",
                },
            )
            if response.status_code >= 400:
                raise HTTPException(status_code=502, detail="Unable to list GitHub repositories")
            page_items = response.json()
            if not isinstance(page_items, list):
                raise HTTPException(status_code=502, detail="GitHub returned invalid repository data")
            repositories.extend(
                {
                    "id": item.get("id"),
                    "full_name": item.get("full_name"),
                    "private": bool(item.get("private")),
                    "default_branch": item.get("default_branch") or "main",
                    "html_url": item.get("html_url"),
                    "updated_at": item.get("updated_at"),
                    "permissions": item.get("permissions") or {},
                }
                for item in page_items
                if isinstance(item, dict)
            )
            if len(page_items) < 100:
                break
    return {"repositories": repositories, "count": len(repositories)}


@router.post("/repositories/import", status_code=201)
def import_github_repository(
    body: GitHubImportRequest,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    full_name = _clean_full_name(body.full_name)
    with _db() as db:
        connection = _connection(db, user["id"])
        token = _decrypt_token(connection["access_token_ciphertext"])
        existing = db.execute(
            "SELECT id FROM repositories WHERE owner_id=? AND github_full_name=? COLLATE NOCASE",
            (user["id"], full_name),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Repository is already imported")

    with httpx.Client(timeout=20) as client:
        response = client.get(
            f"https://api.github.com/repos/{full_name}",
            headers=_github_headers(token),
        )
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="GitHub repository not found or not accessible")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Unable to read GitHub repository")
    metadata = _json_object(response, "GitHub returned invalid repository metadata")
    name = str(metadata.get("name") or full_name.split("/", 1)[1])
    if not _NAME_RE.fullmatch(name):
        raise HTTPException(status_code=422, detail="GitHub repository name is not supported by Amosclaud")
    now = datetime.now(timezone.utc).isoformat()
    with _db() as db:
        if db.execute(
            "SELECT 1 FROM repositories WHERE owner_id=? AND name=? COLLATE NOCASE",
            (user["id"], name),
        ).fetchone():
            name = f"{name}-github"
        cursor = db.execute(
            """INSERT INTO repositories(
                   owner_id,name,description,visibility,default_branch,created_at,updated_at,
                   github_repository_id,github_full_name,github_html_url,
                   github_default_branch,github_last_sync_at,github_last_sync_attempt_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                user["id"],
                name,
                str(metadata.get("description") or ""),
                "private" if metadata.get("private") else "public",
                str(metadata.get("default_branch") or "main"),
                now,
                now,
                int(metadata.get("id") or 0) or None,
                str(metadata.get("full_name") or full_name),
                str(metadata.get("html_url") or ""),
                str(metadata.get("default_branch") or "main"),
                now,
                now,
            ),
        )
        repository_id = cursor.lastrowid
        db.commit()

    path = REPOSITORY_ROOT / str(repository_id)
    try:
        REPOSITORY_ROOT.mkdir(parents=True, exist_ok=True)
        Repo.clone_from(
            _public_remote_url(full_name),
            path,
            env=git_auth_environment(token),
        )
    except Exception as exc:
        shutil.rmtree(path, ignore_errors=True)
        with _db() as db:
            db.execute("DELETE FROM repositories WHERE id=?", (repository_id,))
            db.commit()
        raise HTTPException(status_code=502, detail="GitHub repository clone failed") from exc
    return {
        "id": repository_id,
        "name": name,
        "github_repository_id": int(metadata.get("id") or 0) or None,
        "github_full_name": str(metadata.get("full_name") or full_name),
        "default_branch": metadata.get("default_branch") or "main",
        "workspace_url": f"/workspace/{repository_id}",
    }


def _owned_github_repository(
    db: sqlite3.Connection,
    repository_id: int,
    user_id: int,
) -> sqlite3.Row:
    row = db.execute(
        """SELECT * FROM repositories
           WHERE id=? AND owner_id=? AND github_full_name IS NOT NULL""",
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
    branch = _safe_branch(
        body.branch
        or row["github_default_branch"]
        or row["default_branch"]
        or "main"
    )
    with _repo_lock(repository_id):
        repo = Repo(REPOSITORY_ROOT / str(repository_id))
        if repo.is_dirty(untracked_files=True):
            raise HTTPException(status_code=409, detail="Commit or discard local changes before pulling")
        try:
            repo.git.checkout(branch)
            with authenticated_git(repo, token):
                repo.git.pull("--ff-only", "origin", branch)
        except GitCommandError as exc:
            raise HTTPException(
                status_code=409,
                detail="Pull could not be completed with a fast-forward merge",
            ) from exc
        commit = repo.head.commit.hexsha
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
    }


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
    with _repo_lock(repository_id):
        repo = Repo(REPOSITORY_ROOT / str(repository_id))
        active = None if repo.head.is_detached else repo.active_branch.name
        branch = _safe_branch(body.branch or active or row["github_default_branch"] or "main")
        if branch not in {head.name for head in repo.heads}:
            raise HTTPException(status_code=409, detail=f"Local branch '{branch}' does not exist")
        if repo.is_dirty(untracked_files=True) and active != branch:
            raise HTTPException(
                status_code=409,
                detail="Checkout the requested branch before committing workspace changes",
            )
        if repo.is_dirty(untracked_files=True):
            repo.git.add(A=True)
            with repo.config_writer() as config:
                config.set_value("user", "name", user["name"] or user["email"])
                config.set_value("user", "email", user["email"])
            repo.index.commit(body.commit_message.strip())
        try:
            with authenticated_git(repo, token):
                repo.remote("origin").push(
                    refspec=f"refs/heads/{branch}:refs/heads/{branch}"
                )
        except GitCommandError as exc:
            raise HTTPException(
                status_code=409,
                detail=(
                    "GitHub rejected the push; pull remote changes first or check "
                    "repository permissions"
                ),
            ) from exc
        commit = repo.commit(branch).hexsha
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
    }


@router.post("/repositories/{repository_id}/issues", status_code=201)
async def create_github_issue(
    repository_id: int,
    body: GitHubIssueCreateRequest,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
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
            headers=_github_headers(token),
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
    issue = _json_object(response, "GitHub returned invalid issue metadata")
    return {
        "repository_id": repository_id,
        "github_full_name": repository["github_full_name"],
        "number": issue["number"],
        "title": issue["title"],
        "state": issue["state"],
        "html_url": issue["html_url"],
        "created_at": issue["created_at"],
    }
