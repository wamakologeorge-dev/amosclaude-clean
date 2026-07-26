"""Publish Amosclaud repositories to authorized GitHub users and organizations."""

from __future__ import annotations

import os
import re
import secrets
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import quote, urlencode, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from git import Repo
from git.exc import GitCommandError
from git.remote import PushInfo
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.github_repositories import (
    OAUTH_STATE_COOKIE,
    _connection,
    _current_user,
    _db as _github_db,
    _decrypt_token,
    _public_remote_url,
)
from amoscloud_ai.api.routes.repositories import (
    _db as _repository_db,
    _repo_lock,
    _repo_path,
    _safe_branch,
)
from amoscloud_ai.github_git_auth import authenticated_git
from amoscloud_ai.github_repository_sync import sync_status

router = APIRouter(prefix="/github", tags=["github-organization-publish"])

_OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_GITHUB_SCP_RE = re.compile(r"^(?:[^@]+@)?github\.com:(?P<path>[^?#]+)$", re.I)


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
        raise HTTPException(
            status_code=422,
            detail="Invalid GitHub owner or organization",
        )
    return owner


def _validated_repository_name(value: str) -> str:
    name = value.strip()
    if not _REPOSITORY_RE.fullmatch(name):
        raise HTTPException(
            status_code=422,
            detail="Invalid GitHub repository name",
        )
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
    if isinstance(payload, dict):
        return str(payload.get("message") or fallback)
    return fallback


def _response_object(response: httpx.Response, fallback: str) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=fallback) from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail=fallback)
    return payload


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


def _github_remote_full_name(url: str) -> str | None:
    value = url.strip()
    if not value:
        return None
    scp = _GITHUB_SCP_RE.fullmatch(value)
    if scp:
        path = scp.group("path")
    else:
        parsed = urlparse(value)
        if (parsed.hostname or "").casefold() not in {"github.com", "www.github.com"}:
            raise HTTPException(
                status_code=409,
                detail=(
                    "The local origin is not hosted on GitHub. Amosclaud will not "
                    "replace a GitLab, Bitbucket, or private Git remote."
                ),
            )
        path = parsed.path.lstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", path):
        raise HTTPException(status_code=409, detail="The local GitHub origin is invalid")
    return path


def _validate_local_origin(repo: Repo, full_name: str) -> None:
    if "origin" not in {remote.name for remote in repo.remotes}:
        return
    configured = _github_remote_full_name(repo.remote("origin").url)
    if configured and configured.casefold() != full_name.casefold():
        raise HTTPException(
            status_code=409,
            detail=(
                f"The local origin points to {configured}. Import or unlink that remote "
                "before publishing this workspace to a different GitHub repository."
            ),
        )


def _canonical_origin(repo: Repo, full_name: str):
    _validate_local_origin(repo, full_name)
    if "origin" not in {remote.name for remote in repo.remotes}:
        return repo.create_remote("origin", _public_remote_url(full_name))
    return repo.remote("origin")


def _selected_local_branch(repo: Repo, requested: str | None, fallback: str) -> str:
    active = None if repo.head.is_detached else repo.active_branch.name
    branch = _safe_branch(requested or active or fallback)
    if branch not in {head.name for head in repo.heads}:
        raise HTTPException(
            status_code=409,
            detail=f"Local branch '{branch}' does not exist in this Amosclaud workspace",
        )
    if repo.is_dirty(untracked_files=True) and active != branch:
        raise HTTPException(
            status_code=409,
            detail=(
                "Uncommitted changes belong to a different or detached local branch. "
                "Checkout the requested branch before publishing."
            ),
        )
    return branch


def _push_or_raise(remote, branch: str) -> None:
    rejected = (
        PushInfo.ERROR
        | PushInfo.REJECTED
        | PushInfo.REMOTE_REJECTED
        | PushInfo.REMOTE_FAILURE
    )
    refspec = f"refs/heads/{branch}:refs/heads/{branch}"
    results = remote.push(refspec=refspec, set_upstream=True)
    if not results or any(result.flags & rejected for result in results):
        raise HTTPException(
            status_code=409,
            detail=(
                "GitHub rejected the push. Check organization permissions, branch "
                "protection, or import and pull the target repository first."
            ),
        )


def _rollback_created_repository(
    client: httpx.Client,
    full_name: str,
    headers: dict[str, str],
) -> bool:
    response = client.delete(
        f"https://api.github.com/repos/{full_name}",
        headers=headers,
    )
    return response.status_code == 204


@router.get("/connect-organizations")
def connect_github_organizations(
    request: Request,
    user=Depends(_current_user),
) -> RedirectResponse:
    """Reconnect GitHub with organization visibility and workflow publishing."""

    del user
    client_id = os.getenv("GITHUB_CLIENT_ID")
    if not client_id:
        raise HTTPException(
            status_code=503,
            detail="GitHub integration is not configured",
        )
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
    """List the connected user and organizations visible to the authorization."""

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
    with httpx.Client(timeout=20) as client:
        for page in range(1, 11):
            response = client.get(
                "https://api.github.com/user/orgs",
                headers=_headers(token),
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
                if login and _OWNER_RE.fullmatch(login):
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


@router.get("/repositories/{repository_id}/sync-status")
def github_repository_sync_status(
    repository_id: int,
    user=Depends(_current_user),
) -> dict:
    status = sync_status(repository_id, int(user["id"]))
    if not status:
        raise HTTPException(status_code=404, detail="Repository not found")
    return status


@router.post("/repositories/{repository_id}/publish", status_code=201)
def publish_repository_to_github(
    repository_id: int,
    body: GitHubOrganizationPublishRequest,
    user=Depends(_current_user),
) -> dict:
    """Publish a native Amosclaud repository to an authorized GitHub owner."""

    repository = _owned_repository(repository_id, int(user["id"]))
    token, github_login, _ = _connected_token(int(user["id"]))
    requested_owner = _validated_owner(body.owner)
    requested_name = _validated_repository_name(
        body.repository_name or str(repository["name"])
    )
    requested_full_name = f"{requested_owner}/{requested_name}"
    linked_full_name = str(repository["github_full_name"] or "").strip() or None
    if linked_full_name and linked_full_name.casefold() != requested_full_name.casefold():
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
    with _repo_lock(repository_id):
        try:
            repo = Repo(_repo_path(repository_id))
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail="Local repository storage is not a valid Git repository",
            ) from exc

        branch = _selected_local_branch(
            repo,
            body.branch,
            str(repository["default_branch"] or "main"),
        )
        _validate_local_origin(repo, requested_full_name)
        if repo.is_dirty(untracked_files=True):
            repo.git.add(A=True)
            with repo.config_writer() as config:
                config.set_value("user", "name", user["name"] or user["email"])
                config.set_value("user", "email", user["email"])
            repo.index.commit(body.commit_message.strip())
        local_commit = repo.commit(branch)

        with httpx.Client(timeout=30) as client:
            metadata_response = client.get(
                f"https://api.github.com/repos/{requested_full_name}",
                headers=headers,
            )
            if metadata_response.status_code == 404:
                create_response = client.post(
                    f"https://api.github.com{_creation_path(requested_owner, github_login)}",
                    headers=headers,
                    json={
                        "name": requested_name,
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
                metadata = _response_object(
                    create_response,
                    "GitHub returned invalid repository metadata",
                )
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
                metadata = _response_object(
                    metadata_response,
                    "GitHub returned invalid repository metadata",
                )
                permissions = metadata.get("permissions") or {}
                if not any(
                    bool(permissions.get(name))
                    for name in ("push", "maintain", "admin")
                ):
                    raise HTTPException(
                        status_code=403,
                        detail="The connected GitHub account does not have push access",
                    )
                existing_visibility = (
                    "private" if bool(metadata.get("private")) else "public"
                )
                if existing_visibility != body.visibility:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"The existing GitHub repository is {existing_visibility}, "
                            f"but this publish request selected {body.visibility}. Change "
                            "the GitHub repository visibility or choose the matching value."
                        ),
                    )
                _validate_existing_target(
                    full_name=requested_full_name,
                    linked_full_name=linked_full_name,
                    has_commits=_remote_has_commits(
                        client,
                        requested_full_name,
                        str(metadata.get("default_branch") or "main"),
                        headers,
                    ),
                )

            full_name = str(metadata.get("full_name") or requested_full_name)
            origin = _canonical_origin(repo, full_name)
            try:
                with authenticated_git(repo, token):
                    _push_or_raise(origin, branch)
                if created and str(metadata.get("default_branch") or "") != branch:
                    default_response = client.patch(
                        f"https://api.github.com/repos/{full_name}",
                        headers=headers,
                        json={"default_branch": branch},
                    )
                    if default_response.status_code >= 400:
                        raise HTTPException(
                            status_code=502,
                            detail=(
                                "GitHub received the branch but did not accept it as the "
                                "repository default branch."
                            ),
                        )
            except (GitCommandError, HTTPException) as exc:
                if created:
                    _rollback_created_repository(client, full_name, headers)
                if isinstance(exc, HTTPException):
                    raise
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "GitHub rejected the push. Check branch protection, organization "
                        "authorization, or remote changes."
                    ),
                ) from exc

        github_default_branch = (
            branch if created else str(metadata.get("default_branch") or "main")
        )
        github_repository_id = int(metadata.get("id") or 0) or None
        now = datetime.now(timezone.utc).isoformat()
        html_url = str(metadata.get("html_url") or f"https://github.com/{full_name}")
        with _repository_db() as db:
            db.execute(
                """UPDATE repositories
                   SET github_full_name=?, github_html_url=?, github_default_branch=?,
                       github_repository_id=?, github_last_sync_at=?,
                       github_last_sync_attempt_at=?, updated_at=?
                   WHERE id=? AND owner_id=?""",
                (
                    full_name,
                    html_url,
                    github_default_branch,
                    github_repository_id,
                    now,
                    now,
                    now,
                    repository_id,
                    int(user["id"]),
                ),
            )
            db.commit()

    return {
        "repository_id": repository_id,
        "github_repository_id": github_repository_id,
        "github_full_name": full_name,
        "github_html_url": html_url,
        "owner": full_name.split("/", 1)[0],
        "owner_type": (
            "user"
            if full_name.split("/", 1)[0].casefold() == github_login.casefold()
            else "organization"
        ),
        "branch": branch,
        "default_branch": github_default_branch,
        "commit": local_commit.hexsha,
        "created": created,
        "published_at": now,
    }
