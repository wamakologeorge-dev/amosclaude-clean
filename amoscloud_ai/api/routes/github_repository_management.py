"""Safety-gated GitHub repository administration for connected Amosclaud users."""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from git import Repo
from nacl.public import PublicKey, SealedBox
from pydantic import BaseModel, Field, SecretStr

from amoscloud_ai.api.routes.auth import get_user_from_session
from amoscloud_ai.api.routes.github_repositories import (
    OAUTH_STATE_COOKIE,
    _connection,
    _db,
    _decrypt_token,
    _github_headers,
    _json_object,
    _owned_github_repository,
    _public_remote_url,
)
from amoscloud_ai.api.routes.repositories import REPOSITORY_ROOT, _repo_lock

router = APIRouter(prefix="/github/repository-management", tags=["github-repository-management"])

_ACTIONS_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WEBHOOK_EVENT = re.compile(r"^(?:\*|[a-z][a-z0-9_]*)$")
_INTENT_HEADER = "X-Amosclaud-Intent"
_INTENT_VALUE = "repository-management"
_REQUIRED_MANAGEMENT_SCOPES = "read:user user:email repo workflow admin:repo_hook delete_repo"


@dataclass(frozen=True)
class RepositoryContext:
    repository_id: int
    user_id: int
    full_name: str
    token: str
    scopes: frozenset[str]
    metadata: dict[str, object]


class RepositorySettingsRequest(BaseModel):
    description: str | None = Field(default=None, max_length=350)
    homepage: str | None = Field(default=None, max_length=500)
    default_branch: str | None = Field(default=None, min_length=1, max_length=255)
    visibility: Literal["public", "private"] | None = None
    has_issues: bool | None = None
    has_projects: bool | None = None
    has_wiki: bool | None = None
    has_discussions: bool | None = None
    allow_merge_commit: bool | None = None
    allow_squash_merge: bool | None = None
    allow_rebase_merge: bool | None = None
    allow_auto_merge: bool | None = None
    delete_branch_on_merge: bool | None = None


class ArchiveRequest(BaseModel):
    archived: bool
    confirm_repository: str = Field(..., min_length=3, max_length=200)


class TransferRequest(BaseModel):
    new_owner: str = Field(..., min_length=1, max_length=100)
    new_name: str | None = Field(default=None, min_length=1, max_length=100)
    confirm_repository: str = Field(..., min_length=3, max_length=200)


class DeleteRepositoryRequest(BaseModel):
    confirm_repository: str = Field(..., min_length=3, max_length=200)
    acknowledge_irreversible: bool = False


class SecretValueRequest(BaseModel):
    value: SecretStr = Field(..., min_length=1, max_length=65_536)


class VariableValueRequest(BaseModel):
    value: str = Field(..., max_length=48_000)


class WebhookCreateRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2_000)
    events: list[str] = Field(default_factory=lambda: ["push"], min_length=1, max_length=40)
    active: bool = True
    secret: SecretStr | None = Field(default=None, max_length=1_000)


class WebhookUpdateRequest(BaseModel):
    url: str | None = Field(default=None, min_length=8, max_length=2_000)
    events: list[str] | None = Field(default=None, min_length=1, max_length=40)
    active: bool | None = None
    secret: SecretStr | None = Field(default=None, max_length=1_000)


def _current_user(amos_session: str | None = Cookie(default=None)) -> sqlite3.Row:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to manage GitHub repositories")
    return user


def _mutation_guard(request: Request) -> None:
    if request.headers.get(_INTENT_HEADER) != _INTENT_VALUE:
        raise HTTPException(
            status_code=400,
            detail="Repository management requests require an explicit Amosclaud intent header",
        )


def _scope_set(value: str) -> frozenset[str]:
    return frozenset(part.strip() for part in value.replace(",", " ").split() if part.strip())


def _clean_actions_name(value: str) -> str:
    name = value.strip().upper()
    if not _ACTIONS_NAME.fullmatch(name):
        raise HTTPException(
            status_code=422,
            detail=(
                "Names must start with a letter or underscore and contain only "
                "letters, numbers, and underscores"
            ),
        )
    if name.startswith("GITHUB_"):
        raise HTTPException(status_code=422, detail="Names cannot start with GITHUB_")
    return name


def _clean_webhook_events(events: list[str]) -> list[str]:
    cleaned: list[str] = []
    for raw_event in events:
        event = raw_event.strip().lower()
        if not _WEBHOOK_EVENT.fullmatch(event):
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported webhook event name: {raw_event}",
            )
        if event not in cleaned:
            cleaned.append(event)
    if not cleaned:
        raise HTTPException(status_code=422, detail="Choose at least one webhook event")
    return cleaned


def _clean_webhook_url(value: str) -> str:
    url = value.strip()
    if not url.lower().startswith("https://"):
        raise HTTPException(status_code=422, detail="Webhook URLs must use HTTPS")
    return url


def _require_confirmation(actual: str, supplied: str) -> None:
    if not secrets.compare_digest(actual, supplied.strip()):
        raise HTTPException(
            status_code=422,
            detail=f"Type the full repository name '{actual}' to confirm this operation",
        )


def _encrypt_actions_secret(public_key: str, value: str) -> str:
    try:
        key = PublicKey(base64.b64decode(public_key, validate=True))
        encrypted = SealedBox(key).encrypt(value.encode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="GitHub returned an invalid secret public key",
        ) from exc
    return base64.b64encode(encrypted).decode("ascii")


def _github_error(response: httpx.Response, action: str) -> HTTPException:
    detail = action
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict) and payload.get("message"):
        detail = f"{action}: {payload['message']}"
    if response.status_code == 401:
        return HTTPException(status_code=401, detail="Reconnect GitHub and try again")
    if response.status_code == 403:
        return HTTPException(status_code=403, detail=detail)
    if response.status_code == 404:
        return HTTPException(status_code=404, detail=detail)
    if response.status_code == 422:
        return HTTPException(status_code=422, detail=detail)
    return HTTPException(status_code=502, detail=detail)


def _request_github(
    context: RepositoryContext,
    method: str,
    path: str,
    *,
    action: str,
    json_body: dict[str, object] | None = None,
) -> httpx.Response:
    with httpx.Client(timeout=20) as client:
        response = client.request(
            method,
            f"https://api.github.com{path}",
            headers=_github_headers(context.token),
            json=json_body,
        )
    if response.status_code >= 400:
        raise _github_error(response, action)
    return response


def _repository_context(
    repository_id: int,
    user: sqlite3.Row,
    *,
    require_admin: bool = True,
) -> RepositoryContext:
    with _db() as db:
        repository = _owned_github_repository(db, repository_id, int(user["id"]))
        connection = _connection(db, int(user["id"]))
        token = _decrypt_token(connection["access_token_ciphertext"])
        scopes = _scope_set(str(connection["scopes"] or ""))
    full_name = str(repository["github_full_name"])
    with httpx.Client(timeout=20) as client:
        response = client.get(
            f"https://api.github.com/repos/{full_name}",
            headers=_github_headers(token),
        )
    if response.status_code >= 400:
        raise _github_error(response, "Unable to read repository administration settings")
    metadata = _json_object(response, "GitHub returned invalid repository metadata")
    permissions = metadata.get("permissions")
    can_admin = bool(isinstance(permissions, dict) and permissions.get("admin"))
    if require_admin and not can_admin:
        raise HTTPException(
            status_code=403,
            detail="GitHub administrator permission is required for repository developer settings",
        )
    return RepositoryContext(
        repository_id=repository_id,
        user_id=int(user["id"]),
        full_name=full_name,
        token=token,
        scopes=scopes,
        metadata=metadata,
    )


def _ensure_audit_schema(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS github_repository_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            repository_id INTEGER,
            github_full_name TEXT NOT NULL,
            operation TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )""")


def _audit(context: RepositoryContext, operation: str, details: dict[str, object]) -> None:
    with _db() as db:
        _ensure_audit_schema(db)
        db.execute(
            """INSERT INTO github_repository_audit_log
               (user_id,repository_id,github_full_name,operation,details_json,created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                context.user_id,
                context.repository_id,
                context.full_name,
                operation,
                json.dumps(details, sort_keys=True, separators=(",", ":")),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        db.commit()


def _update_local_metadata(repository_id: int, metadata: dict[str, object]) -> None:
    full_name = str(metadata.get("full_name") or "")
    now = datetime.now(timezone.utc).isoformat()
    with _db() as db:
        db.execute(
            """UPDATE repositories
               SET github_full_name=?,github_html_url=?,github_default_branch=?,
                   default_branch=?,visibility=?,updated_at=?
               WHERE id=?""",
            (
                full_name or None,
                str(metadata.get("html_url") or ""),
                str(metadata.get("default_branch") or "main"),
                str(metadata.get("default_branch") or "main"),
                "private" if metadata.get("private") else "public",
                now,
                repository_id,
            ),
        )
        db.commit()


def _update_transferred_repository(context: RepositoryContext, metadata: dict[str, object]) -> None:
    new_full_name = str(metadata.get("full_name") or "").strip()
    if not new_full_name:
        return
    _update_local_metadata(context.repository_id, metadata)
    path = REPOSITORY_ROOT / str(context.repository_id)
    if not path.exists():
        return
    with _repo_lock(context.repository_id):
        repo = Repo(path)
        try:
            repo.remote("origin").set_url(_public_remote_url(new_full_name))
        except ValueError:
            repo.create_remote("origin", _public_remote_url(new_full_name))


def _remove_local_repository(context: RepositoryContext) -> None:
    path = REPOSITORY_ROOT / str(context.repository_id)
    with _repo_lock(context.repository_id):
        shutil.rmtree(path, ignore_errors=True)
    with _db() as db:
        db.execute(
            "DELETE FROM repositories WHERE id=? AND owner_id=?",
            (context.repository_id, context.user_id),
        )
        db.commit()


def _summary(metadata: dict[str, object], scopes: frozenset[str]) -> dict[str, object]:
    permissions = (
        metadata.get("permissions") if isinstance(metadata.get("permissions"), dict) else {}
    )
    return {
        "id": metadata.get("id"),
        "full_name": metadata.get("full_name"),
        "html_url": metadata.get("html_url"),
        "description": metadata.get("description") or "",
        "homepage": metadata.get("homepage") or "",
        "private": bool(metadata.get("private")),
        "visibility": metadata.get("visibility")
        or ("private" if metadata.get("private") else "public"),
        "archived": bool(metadata.get("archived")),
        "default_branch": metadata.get("default_branch") or "main",
        "has_issues": bool(metadata.get("has_issues")),
        "has_projects": bool(metadata.get("has_projects")),
        "has_wiki": bool(metadata.get("has_wiki")),
        "has_discussions": bool(metadata.get("has_discussions")),
        "allow_merge_commit": bool(metadata.get("allow_merge_commit")),
        "allow_squash_merge": bool(metadata.get("allow_squash_merge")),
        "allow_rebase_merge": bool(metadata.get("allow_rebase_merge")),
        "allow_auto_merge": bool(metadata.get("allow_auto_merge")),
        "delete_branch_on_merge": bool(metadata.get("delete_branch_on_merge")),
        "permissions": permissions,
        "oauth_scopes": sorted(scopes),
        "delete_ready": "delete_repo" in scopes,
    }


@router.get("/connect")
def connect_repository_management(
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
            "scope": _REQUIRED_MANAGEMENT_SCOPES,
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


@router.get("/imported")
def list_imported_repository_management_targets(
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, object]:
    with _db() as db:
        rows = db.execute(
            """SELECT id,github_full_name FROM repositories
               WHERE owner_id=? AND github_full_name IS NOT NULL
               ORDER BY updated_at DESC""",
            (int(user["id"]),),
        ).fetchall()
    return {
        "repositories": [
            {"repository_id": int(row["id"]), "github_full_name": str(row["github_full_name"])}
            for row in rows
        ]
    }


@router.get("/repositories/{repository_id}")
def repository_management_summary(
    repository_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, object]:
    context = _repository_context(repository_id, user, require_admin=False)
    return {
        "repository_id": repository_id,
        "can_admin": bool(
            isinstance(context.metadata.get("permissions"), dict)
            and context.metadata["permissions"].get("admin")
        ),
        "repository": _summary(context.metadata, context.scopes),
        "management_connect_url": "/api/v1/github/repository-management/connect",
    }


@router.patch("/repositories/{repository_id}/settings")
def update_repository_settings(
    repository_id: int,
    body: RepositorySettingsRequest,
    request: Request,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, object]:
    _mutation_guard(request)
    context = _repository_context(repository_id, user)
    payload = body.model_dump(exclude_none=True)
    if "description" in payload:
        payload["description"] = str(payload["description"]).strip()
    if "homepage" in payload:
        payload["homepage"] = str(payload["homepage"]).strip()
    if "default_branch" in payload:
        payload["default_branch"] = str(payload["default_branch"]).strip()
    visibility = payload.pop("visibility", None)
    if visibility is not None:
        payload["private"] = visibility == "private"
    if not payload:
        raise HTTPException(
            status_code=422,
            detail="Choose at least one repository setting to update",
        )
    response = _request_github(
        context,
        "PATCH",
        f"/repos/{context.full_name}",
        action="GitHub rejected the repository settings update",
        json_body=payload,
    )
    metadata = _json_object(response, "GitHub returned invalid repository metadata")
    _update_local_metadata(repository_id, metadata)
    _audit(context, "settings.update", {"fields": sorted(payload)})
    return {"repository_id": repository_id, "repository": _summary(metadata, context.scopes)}


@router.post("/repositories/{repository_id}/archive")
def set_repository_archive_state(
    repository_id: int,
    body: ArchiveRequest,
    request: Request,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, object]:
    _mutation_guard(request)
    context = _repository_context(repository_id, user)
    _require_confirmation(context.full_name, body.confirm_repository)
    response = _request_github(
        context,
        "PATCH",
        f"/repos/{context.full_name}",
        action="GitHub rejected the archive change",
        json_body={"archived": body.archived},
    )
    metadata = _json_object(response, "GitHub returned invalid repository metadata")
    _update_local_metadata(repository_id, metadata)
    _audit(context, "repository.archive" if body.archived else "repository.unarchive", {})
    return {"repository_id": repository_id, "repository": _summary(metadata, context.scopes)}


@router.post("/repositories/{repository_id}/transfer", status_code=202)
def transfer_repository(
    repository_id: int,
    body: TransferRequest,
    request: Request,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, object]:
    _mutation_guard(request)
    context = _repository_context(repository_id, user)
    _require_confirmation(context.full_name, body.confirm_repository)
    payload: dict[str, object] = {"new_owner": body.new_owner.strip()}
    if body.new_name:
        payload["new_name"] = body.new_name.strip()
    response = _request_github(
        context,
        "POST",
        f"/repos/{context.full_name}/transfer",
        action="GitHub rejected the repository transfer",
        json_body=payload,
    )
    metadata = _json_object(response, "GitHub returned invalid transfer metadata")
    _update_transferred_repository(context, metadata)
    _audit(
        context,
        "repository.transfer",
        {"new_owner": payload["new_owner"], "new_name": payload.get("new_name")},
    )
    return {
        "repository_id": repository_id,
        "status": "transfer_started",
        "repository": _summary(metadata, context.scopes),
    }


@router.delete("/repositories/{repository_id}", status_code=204)
def delete_repository(
    repository_id: int,
    body: DeleteRepositoryRequest,
    request: Request,
    user: sqlite3.Row = Depends(_current_user),
) -> Response:
    _mutation_guard(request)
    context = _repository_context(repository_id, user)
    _require_confirmation(context.full_name, body.confirm_repository)
    if not body.acknowledge_irreversible:
        raise HTTPException(
            status_code=422,
            detail="Confirm that repository deletion is irreversible",
        )
    if "delete_repo" not in context.scopes:
        raise HTTPException(
            status_code=403,
            detail="Reconnect GitHub with repository deletion permission before deleting",
        )
    _request_github(
        context,
        "DELETE",
        f"/repos/{context.full_name}",
        action="GitHub rejected repository deletion",
    )
    _audit(context, "repository.delete", {"local_workspace_removed": True})
    _remove_local_repository(context)
    return Response(status_code=204)


@router.get("/repositories/{repository_id}/secrets")
def list_repository_secrets(
    repository_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, object]:
    context = _repository_context(repository_id, user)
    response = _request_github(
        context,
        "GET",
        f"/repos/{context.full_name}/actions/secrets?per_page=100",
        action="Unable to list repository secrets",
    )
    payload = _json_object(response, "GitHub returned invalid secret metadata")
    secrets_list = payload.get("secrets") if isinstance(payload.get("secrets"), list) else []
    return {
        "repository_id": repository_id,
        "total_count": int(payload.get("total_count") or len(secrets_list)),
        "secrets": [
            {
                "name": item.get("name"),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
            }
            for item in secrets_list
            if isinstance(item, dict)
        ],
    }


@router.put("/repositories/{repository_id}/secrets/{secret_name}")
def put_repository_secret(
    repository_id: int,
    secret_name: str,
    body: SecretValueRequest,
    request: Request,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, object]:
    _mutation_guard(request)
    context = _repository_context(repository_id, user)
    name = _clean_actions_name(secret_name)
    key_response = _request_github(
        context,
        "GET",
        f"/repos/{context.full_name}/actions/secrets/public-key",
        action="Unable to obtain the GitHub secret encryption key",
    )
    key_payload = _json_object(key_response, "GitHub returned invalid secret key metadata")
    encrypted_value = _encrypt_actions_secret(
        str(key_payload.get("key") or ""),
        body.value.get_secret_value(),
    )
    response = _request_github(
        context,
        "PUT",
        f"/repos/{context.full_name}/actions/secrets/{name}",
        action="GitHub rejected the repository secret",
        json_body={
            "encrypted_value": encrypted_value,
            "key_id": str(key_payload.get("key_id") or ""),
        },
    )
    _audit(context, "secret.put", {"name": name})
    return {
        "repository_id": repository_id,
        "name": name,
        "created": response.status_code == 201,
        "value_returned": False,
    }


@router.delete("/repositories/{repository_id}/secrets/{secret_name}", status_code=204)
def delete_repository_secret(
    repository_id: int,
    secret_name: str,
    request: Request,
    user: sqlite3.Row = Depends(_current_user),
) -> Response:
    _mutation_guard(request)
    context = _repository_context(repository_id, user)
    name = _clean_actions_name(secret_name)
    _request_github(
        context,
        "DELETE",
        f"/repos/{context.full_name}/actions/secrets/{name}",
        action="GitHub rejected repository secret deletion",
    )
    _audit(context, "secret.delete", {"name": name})
    return Response(status_code=204)


@router.get("/repositories/{repository_id}/variables")
def list_repository_variables(
    repository_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, object]:
    context = _repository_context(repository_id, user)
    response = _request_github(
        context,
        "GET",
        f"/repos/{context.full_name}/actions/variables?per_page=30",
        action="Unable to list repository variables",
    )
    payload = _json_object(response, "GitHub returned invalid variable metadata")
    variables = payload.get("variables") if isinstance(payload.get("variables"), list) else []
    return {
        "repository_id": repository_id,
        "total_count": int(payload.get("total_count") or len(variables)),
        "variables": [item for item in variables if isinstance(item, dict)],
    }


@router.put("/repositories/{repository_id}/variables/{variable_name}")
def put_repository_variable(
    repository_id: int,
    variable_name: str,
    body: VariableValueRequest,
    request: Request,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, object]:
    _mutation_guard(request)
    context = _repository_context(repository_id, user)
    name = _clean_actions_name(variable_name)
    with httpx.Client(timeout=20) as client:
        existing = client.get(
            f"https://api.github.com/repos/{context.full_name}/actions/variables/{name}",
            headers=_github_headers(context.token),
        )
    if existing.status_code == 404:
        response = _request_github(
            context,
            "POST",
            f"/repos/{context.full_name}/actions/variables",
            action="GitHub rejected the repository variable",
            json_body={"name": name, "value": body.value},
        )
        created = response.status_code == 201
    elif existing.status_code >= 400:
        raise _github_error(existing, "Unable to inspect the repository variable")
    else:
        _request_github(
            context,
            "PATCH",
            f"/repos/{context.full_name}/actions/variables/{name}",
            action="GitHub rejected the repository variable update",
            json_body={"name": name, "value": body.value},
        )
        created = False
    _audit(context, "variable.put", {"name": name, "created": created})
    return {"repository_id": repository_id, "name": name, "value": body.value, "created": created}


@router.delete("/repositories/{repository_id}/variables/{variable_name}", status_code=204)
def delete_repository_variable(
    repository_id: int,
    variable_name: str,
    request: Request,
    user: sqlite3.Row = Depends(_current_user),
) -> Response:
    _mutation_guard(request)
    context = _repository_context(repository_id, user)
    name = _clean_actions_name(variable_name)
    _request_github(
        context,
        "DELETE",
        f"/repos/{context.full_name}/actions/variables/{name}",
        action="GitHub rejected repository variable deletion",
    )
    _audit(context, "variable.delete", {"name": name})
    return Response(status_code=204)


@router.get("/repositories/{repository_id}/webhooks")
def list_repository_webhooks(
    repository_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, object]:
    context = _repository_context(repository_id, user)
    response = _request_github(
        context,
        "GET",
        f"/repos/{context.full_name}/hooks?per_page=100",
        action="Unable to list repository webhooks",
    )
    payload = response.json()
    if not isinstance(payload, list):
        raise HTTPException(status_code=502, detail="GitHub returned invalid webhook metadata")
    return {
        "repository_id": repository_id,
        "webhooks": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "active": bool(item.get("active")),
                "events": item.get("events") or [],
                "url": (
                    (item.get("config") or {}).get("url")
                    if isinstance(item.get("config"), dict)
                    else None
                ),
                "content_type": (
                    (item.get("config") or {}).get("content_type")
                    if isinstance(item.get("config"), dict)
                    else None
                ),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
                "last_response": item.get("last_response") or {},
            }
            for item in payload
            if isinstance(item, dict)
        ],
    }


@router.post("/repositories/{repository_id}/webhooks", status_code=201)
def create_repository_webhook(
    repository_id: int,
    body: WebhookCreateRequest,
    request: Request,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, object]:
    _mutation_guard(request)
    context = _repository_context(repository_id, user)
    config: dict[str, str] = {
        "url": _clean_webhook_url(body.url),
        "content_type": "json",
        "insecure_ssl": "0",
    }
    if body.secret is not None and body.secret.get_secret_value():
        config["secret"] = body.secret.get_secret_value()
    response = _request_github(
        context,
        "POST",
        f"/repos/{context.full_name}/hooks",
        action="GitHub rejected the repository webhook",
        json_body={
            "name": "web",
            "active": body.active,
            "events": _clean_webhook_events(body.events),
            "config": config,
        },
    )
    hook = _json_object(response, "GitHub returned invalid webhook metadata")
    _audit(
        context,
        "webhook.create",
        {"hook_id": hook.get("id"), "url": config["url"], "events": hook.get("events") or []},
    )
    return {
        "repository_id": repository_id,
        "id": hook.get("id"),
        "active": bool(hook.get("active")),
        "events": hook.get("events") or [],
        "url": (
            (hook.get("config") or {}).get("url")
            if isinstance(hook.get("config"), dict)
            else config["url"]
        ),
        "secret_returned": False,
    }


@router.patch("/repositories/{repository_id}/webhooks/{hook_id}")
def update_repository_webhook(
    repository_id: int,
    hook_id: int,
    body: WebhookUpdateRequest,
    request: Request,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, object]:
    _mutation_guard(request)
    context = _repository_context(repository_id, user)
    if hook_id < 1:
        raise HTTPException(status_code=422, detail="Webhook ID must be positive")
    payload: dict[str, object] = {}
    if body.active is not None:
        payload["active"] = body.active
    if body.events is not None:
        payload["events"] = _clean_webhook_events(body.events)
    config: dict[str, str] = {}
    if body.url is not None:
        config.update(
            {"url": _clean_webhook_url(body.url), "content_type": "json", "insecure_ssl": "0"}
        )
    if body.secret is not None and body.secret.get_secret_value():
        config["secret"] = body.secret.get_secret_value()
    if config:
        payload["config"] = config
    if not payload:
        raise HTTPException(status_code=422, detail="Choose at least one webhook setting to update")
    response = _request_github(
        context,
        "PATCH",
        f"/repos/{context.full_name}/hooks/{hook_id}",
        action="GitHub rejected the webhook update",
        json_body=payload,
    )
    hook = _json_object(response, "GitHub returned invalid webhook metadata")
    _audit(context, "webhook.update", {"hook_id": hook_id, "fields": sorted(payload)})
    return {
        "repository_id": repository_id,
        "id": hook.get("id") or hook_id,
        "active": bool(hook.get("active")),
        "events": hook.get("events") or [],
        "url": (
            (hook.get("config") or {}).get("url") if isinstance(hook.get("config"), dict) else None
        ),
        "secret_returned": False,
    }


@router.post("/repositories/{repository_id}/webhooks/{hook_id}/ping", status_code=204)
def ping_repository_webhook(
    repository_id: int,
    hook_id: int,
    request: Request,
    user: sqlite3.Row = Depends(_current_user),
) -> Response:
    _mutation_guard(request)
    context = _repository_context(repository_id, user)
    if hook_id < 1:
        raise HTTPException(status_code=422, detail="Webhook ID must be positive")
    _request_github(
        context,
        "POST",
        f"/repos/{context.full_name}/hooks/{hook_id}/pings",
        action="GitHub could not ping the repository webhook",
    )
    _audit(context, "webhook.ping", {"hook_id": hook_id})
    return Response(status_code=204)


@router.delete("/repositories/{repository_id}/webhooks/{hook_id}", status_code=204)
def delete_repository_webhook(
    repository_id: int,
    hook_id: int,
    request: Request,
    user: sqlite3.Row = Depends(_current_user),
) -> Response:
    _mutation_guard(request)
    context = _repository_context(repository_id, user)
    if hook_id < 1:
        raise HTTPException(status_code=422, detail="Webhook ID must be positive")
    _request_github(
        context,
        "DELETE",
        f"/repos/{context.full_name}/hooks/{hook_id}",
        action="GitHub rejected repository webhook deletion",
    )
    _audit(context, "webhook.delete", {"hook_id": hook_id})
    return Response(status_code=204)
