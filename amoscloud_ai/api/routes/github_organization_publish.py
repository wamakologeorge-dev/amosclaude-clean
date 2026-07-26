"""Publish Amosclaud repositories to authorized GitHub users and organizations."""

from __future__ import annotations

import os
import re
import secrets
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from git import Repo
from git.exc import GitCommandError
from git.remote import PushInfo
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.github_repositories import (
    OAUTH_STATE_COOKIE,
    _authenticated_clone_url,
    _connection,
    _current_user,
    _db as _github_db,
    _decrypt_token,
    _public_remote_url,
)
from amoscloud_ai.api.routes.repositories import _db as _repository_db
from amoscloud_ai.api.routes.repositories import _repo_path, _safe_branch

router = APIRouter(prefix="/github", tags=["github-organization-publish"])

_OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class GitHubOrganizationPublishRequest(BaseModel):
    owner: str = Field(..., min_length=1, max_length=100)
    repository_name: str | None = Field(default=None, max_length=100)
    visibility: Literal["private", "public"] = "private"
    branch: str | None = Field(default=None, max_length=200)
    commit_message: str = Field(
        default="Publish Amosclaud work to GitHub",
        min_length=1,
        max_length=200,
    )


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _scope_set(value: str) -> set[str]:
    return {
        item.strip()
        for chunk in value.split(",")
        for item in chunk.split()
        if item.strip()
    }


def _creation_path(owner: str, github_login: str) -> str:
    if owner.casefold() == github_login.casefold():
        return "/user/repos"
    return f"/orgs/{owner}/repos"


def _validated_owner(value: str) -> str:
    owner = value.strip()
    if not _OWNER_RE.fullmatch(owner):
        raise HTTPException(status_code=422, detail="Invalid GitHub owner or organization")
    return owner


def _validated_repository_name(value: str) -> str:
    name = value.strip()
    if not _REPOSITORY_RE.fullmatch(name):
        raise HTTPException(status_code=422, detail="Invalid GitHub repository name")
    return name


def _owned_repository(repository_id: int, user_id: int):
    with _repository_db() as db:
        row = db.execute(
            "SELECT * FROM repositories WHERE id=? AND owner_id=?",
            (repository_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Repository not found")
    return row


def _connected_token(user_id: int) -> tuple[str, str, str]:
    with _github_db() as db:
        connection = _connection(db, user_id)
        return (
            _decrypt_token(connection["access_token_ciphertext"]),
            str(connection["github_login"]),
            str(connection["scopes"] or ""),
        )


def _github_detail(response: httpx.Response, fallback: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        return fallback
    message = payload.get("message") if isinstance(payload, dict) else None
    return str(message or fallback)


def _remote_has_commits(
    client: httpx.Client,
    full_name: str,
    default_branch: str,
    headers: dict[str, str],
) -> bool:
    response = client.get(
        f"https://api.github.com/repos/{full_name}/git/ref/heads/{quote(default_branch, safe='')}",
        headers=headers,
    )
    if response.status_code == 200:
        return True
    if response.status_code in {404, 409}:
        return False
    if response.status_code in {401, 403}:
        raise HTTPException(
            status_code=403,
            detail="GitHub authorization cannot inspect the target repository",
        )
    raise HTTPException(
        status_code=502,
        detail="Unable to verify the target GitHub repository history",
    )


def _validate_existing_target(
    *,
    full_name: str,
    linked_full_name: str | None,
    has_commits: bool,
) -> None:
    if not has_commits:
        return
    if linked_full_name and linked_full_name.casefold() == full_name.casefold():
        return
    raise HTTPException(
        status_code=409,
        detail=(
            "The target repository already has history. Import that GitHub repository "
            "into Amosclaud first, then make changes and push them back. Amosclaud will "
            "not overwrite unrelated organization history."
        ),
    )


def _push_or_raise(remote, branch: str) -> None:
    rejected = PushInfo.ERROR | PushInfo.REJECTED | PushInfo.REMOTE_REJECTED
    results = remote.push(refspec=f"HEAD:refs/heads/{branch}")
    if not results or any(result.flags & rejected for result in results):
        raise HTTPException(
            status_code=409,
            detail=(
                "GitHub rejected the push. Check organization permissions, branch "
                "protection, or import and pull the target repository first."
            ),
        )


@router.get("/connect-organizations")
def connect_github_organizations(
    request: Request,
    user=Depends(_current_user),
) -> RedirectResponse:
    """Reconnect GitHub with organization visibility and workflow publishing."""

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
            "scope": "read:user user:email repo workflow read:org",
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


@router.get("/organizations")
def list_github_publish_targets(user=Depends(_current_user)) -> dict:
    """List the connected user and GitHub organizations visible to the token."""

    token, github_login, scopes = _connected_token(int(user["id"]))
    targets = [
        {
            "login": github_login,
            "kind": "user",
            "avatar_url": None,
            "description": "Personal GitHub account",
        }
    ]
    reconnect_required = not {"repo", "workflow", "read:org"}.issubset(
        _scope_set(scopes)
    )
    headers = _headers(token)
    with httpx.Client(timeout=20) as client:
        for page in range(1, 11):
            response = client.get(
                "https://api.github.com/user/orgs",
                headers=headers,
                params={"per_page": 100, "page": page},
            )
            if response.status_code == 401:
                raise HTTPException(
                    status_code=401,
                    detail="GitHub authorization expired; reconnect GitHub",
                )
            if response.status_code == 403:
                reconnect_required = True
                break
            if response.status_code >= 400:
                raise HTTPException(
                    status_code=502,
                    detail="Unable to list GitHub organizations",
                )
            organizations = response.json()
            if not isinstance(organizations, list):
                raise HTTPException(
                    status_code=502,
                    detail="GitHub returned an invalid organization list",
                )
            for organization in organizations:
                login = str(organization.get("login") or "").strip()
                if not login or not _OWNER_RE.fullmatch(login):
                    continue
                targets.append(
                    {
                        "login": login,
                        "kind": "organization",
                        "avatar_url": organization.get("avatar_url"),
                        "description": organization.get("description")
                        or "GitHub organization",
                    }
                )
            if len(organizations) < 100:
                break
    return {
        "connected_as": github_login,
        "targets": targets,
        "reconnect_required": reconnect_required,
        "reconnect_url": "/api/v1/github/connect-organizations",
        "permission_note": (
            "GitHub verifies repository creation and push permission at publish time. "
            "Organization policy, SSO, or app approval may still be required."
        ),
    }


@router.post("/repositories/{repository_id}/publish", status_code=201)
def publish_repository_to_github(
    repository_id: int,
    body: GitHubOrganizationPublishRequest,
    user=Depends(_current_user),
) -> dict:
    """Publish a native Amosclaud repository to an authorized GitHub owner."""

    repository = _owned_repository(repository_id, int(user["id"]))
    token, github_login, _ = _connected_token(int(user["id"]))
    owner = _validated_owner(body.owner)
    repository_name = _validated_repository_name(
        body.repository_name or str(repository["name"])
    )
    full_name = f"{owner}/{repository_name}"
    linked_full_name = str(repository["github_full_name"] or "").strip() or None
    if linked_full_name and linked_full_name.casefold() != full_name.casefold():
        raise HTTPException(
            status_code=409,
            detail=(
                f"This Amosclaud repository is already linked to {linked_full_name}. "
                "Create a separate Amosclaud repository before publishing a copy to "
                "another GitHub owner."
            ),
        )

    headers = _headers(token)
    created = False
    with httpx.Client(timeout=30) as client:
        metadata_response = client.get(
            f"https://api.github.com/repos/{full_name}",
            headers=headers,
        )
        if metadata_response.status_code == 404:
            create_response = client.post(
                f"https://api.github.com{_creation_path(owner, github_login)}",
                headers=headers,
                json={
                    "name": repository_name,
                    "description": str(repository["description"] or ""),
                    "private": body.visibility == "private",
                    "auto_init": False,
                },
            )
            if create_response.status_code in {401, 403}:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        "GitHub did not authorize repository creation for this owner. "
                        "Reconnect GitHub, approve Amosclaud for the organization, and "
                        "confirm that your organization role may create repositories."
                    ),
                )
            if create_response.status_code >= 400:
                raise HTTPException(
                    status_code=409 if create_response.status_code == 422 else 502,
                    detail=_github_detail(
                        create_response,
                        "GitHub repository creation failed",
                    ),
                )
            metadata = create_response.json()
            created = True
        elif metadata_response.status_code in {401, 403}:
            raise HTTPException(
                status_code=403,
                detail="GitHub did not authorize access to the target repository",
            )
        elif metadata_response.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail="Unable to inspect the target GitHub repository",
            )
        else:
            metadata = metadata_response.json()
            permissions = metadata.get("permissions") or {}
            if not any(
                bool(permissions.get(name))
                for name in ("push", "maintain", "admin")
            ):
                raise HTTPException(
                    status_code=403,
                    detail="The connected GitHub account does not have push access",
                )
            default_branch = str(metadata.get("default_branch") or "main")
            _validate_existing_target(
                full_name=full_name,
                linked_full_name=linked_full_name,
                has_commits=_remote_has_commits(
                    client,
                    full_name,
                    default_branch,
                    headers,
                ),
            )

    path = _repo_path(repository_id)
    try:
        repo = Repo(path)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Local repository storage is not a valid Git repository",
        ) from exc

    branch = _safe_branch(
        body.branch
        or (
            repo.active_branch.name
            if not repo.head.is_detached
            else str(repository["default_branch"] or "main")
        )
    )
    if repo.is_dirty(untracked_files=True):
        repo.git.add(A=True)
        with repo.config_writer() as config:
            config.set_value("user", "name", user["name"] or user["email"])
            config.set_value("user", "email", user["email"])
        repo.index.commit(body.commit_message.strip())

    remote_name = "origin" if linked_full_name else "amosclaud-publish"
    authenticated_url = _authenticated_clone_url(full_name, token)
    public_url = _public_remote_url(full_name)
    if remote_name in [remote.name for remote in repo.remotes]:
        remote = repo.remote(remote_name)
        original_url = remote.url
    else:
        remote = repo.create_remote(remote_name, public_url)
        original_url = public_url
    try:
        remote.set_url(authenticated_url)
        _push_or_raise(remote, branch)
    except GitCommandError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "GitHub rejected the push. Check branch protection, organization "
                "authorization, or remote changes."
            ),
        ) from exc
    finally:
        remote.set_url(original_url or public_url)

    now = datetime.now(timezone.utc).isoformat()
    html_url = str(metadata.get("html_url") or f"https://github.com/{full_name}")
    with _repository_db() as db:
        db.execute(
            """UPDATE repositories
               SET github_full_name=?, github_html_url=?, github_default_branch=?,
                   github_last_sync_at=?, updated_at=?
               WHERE id=? AND owner_id=?""",
            (
                full_name,
                html_url,
                branch,
                now,
                now,
                repository_id,
                int(user["id"]),
            ),
        )
        db.commit()
    return {
        "repository_id": repository_id,
        "github_full_name": full_name,
        "github_html_url": html_url,
        "owner": owner,
        "owner_type": "user" if owner.casefold() == github_login.casefold() else "organization",
        "branch": branch,
        "commit": repo.head.commit.hexsha,
        "created": created,
        "published_at": now,
    }
