"""HTTP API for the shared Amosclaud identity authority."""

from __future__ import annotations

import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import _connect, get_user_from_session
from amoscloud_ai.core import amosclaud_action
from amoscloud_ai.core import amosclaud_authority as authority

router = APIRouter(prefix="/amosclaud/authority", tags=["amosclaud-authority"])


class PlatformCredentialCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    type: Literal["api_key", "token", "action"] = "token"
    scopes: list[str] = Field(..., min_length=1, max_length=30)


class WorkspaceGrantCreate(BaseModel):
    provider: str = Field(..., min_length=1, max_length=64)
    subject: str = Field(..., min_length=1, max_length=254)
    scopes: list[str] = Field(..., min_length=1, max_length=30)
    expires_in_days: int = Field(
        ...,
        ge=authority.MIN_THIRD_PARTY_GRANT_DAYS,
        le=authority.MAX_THIRD_PARTY_GRANT_DAYS,
    )


class WorkspaceGrantRotate(BaseModel):
    expires_in_days: int = Field(
        default=authority.MIN_THIRD_PARTY_GRANT_DAYS,
        ge=authority.MIN_THIRD_PARTY_GRANT_DAYS,
        le=authority.MAX_THIRD_PARTY_GRANT_DAYS,
    )


def _current_user(
    amos_session: str | None = Cookie(default=None),
) -> sqlite3.Row:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to manage Amosclaud authority")
    return user


def _authority_error(exc: authority.AuthorityError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


def _workspace_admin(workspace_id: str, user: sqlite3.Row) -> dict[str, Any]:
    """Require the existing workspace owner or a platform administrator."""

    with _connect() as db:
        tables = {
            str(row[0])
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        matches: list[sqlite3.Row] = []
        if "workspaces" in tables:
            columns = {
                str(row[1]) for row in db.execute("PRAGMA table_info(workspaces)").fetchall()
            }
            repository_id = "repository_id" if "repository_id" in columns else "NULL"
            status_clause = " AND status!='deleted'" if "status" in columns else ""
            matches.extend(
                db.execute(
                    f"""SELECT id,user_id AS owner_id,{repository_id} AS repository_id,
                              'workspaces' AS source
                       FROM workspaces
                       WHERE id=?{status_clause}""",
                    (workspace_id,),
                ).fetchall()
            )
        if "cloud_workspaces" in tables:
            matches.extend(
                db.execute(
                    """SELECT id,owner_id,repository_id,'cloud_workspaces' AS source
                       FROM cloud_workspaces WHERE id=?""",
                    (workspace_id,),
                ).fetchall()
            )

    if not matches:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if bool(user["is_admin"]) or any(
        int(row["owner_id"]) == int(user["id"]) for row in matches
    ):
        return dict(matches[0])

    repository_ids = {
        int(row["repository_id"])
        for row in matches
        if row["repository_id"] is not None
    }
    if repository_ids and {"organization_repositories", "organization_members"} <= tables:
        placeholders = ",".join("?" for _ in repository_ids)
        with _connect() as db:
            member_columns = {
                str(row[1])
                for row in db.execute("PRAGMA table_info(organization_members)").fetchall()
            }
            member_status = " AND om.status='active'" if "status" in member_columns else ""
            organization_admin = db.execute(
                f"""SELECT 1
                    FROM organization_repositories ores
                    JOIN organization_members om
                      ON om.organization_id=ores.organization_id
                    WHERE ores.repository_id IN ({placeholders})
                      AND om.user_id=?
                      AND om.role IN ('owner','admin')
                      {member_status}
                    LIMIT 1""",
                (*sorted(repository_ids), int(user["id"])),
            ).fetchone()
        if organization_admin:
            return dict(matches[0])
    raise HTTPException(
        status_code=403,
        detail="Workspace owner or Amosclaud platform administrator access required",
    )


def _raw_credential(request: Request) -> str:
    api_key = request.headers.get("x-api-key", "").strip()
    if api_key:
        return api_key
    authorization = request.headers.get("authorization", "").strip()
    scheme, separator, value = authorization.partition(" ")
    if separator and scheme.lower() == "bearer" and value.strip():
        return value.strip()
    raise HTTPException(
        status_code=401,
        detail="Provide an Amosclaud authority credential using Bearer or X-API-Key",
    )


@router.get("/manifest")
def authority_manifest() -> dict[str, Any]:
    """Describe the first-party authority without revealing any secret."""

    return {
        "product": "Amosclaud",
        "authority": "Amosclaud Authority",
        "credential_types": {
            "api_key": {
                "prefix": "amos_api_",
                "expiration": "manual_revocation",
            },
            "token": {
                "prefix": "amos_token_",
                "expiration": "manual_revocation",
            },
            "action": {
                "prefix": "amos_action_",
                "expiration": "manual_revocation",
            },
        },
        "shared_verifier": "/api/v1/amosclaud/authority/verify",
        "product_scopes": sorted(authority.PLATFORM_SCOPES),
        "third_party_grants": {
            "prefix": "amos_ext_",
            "workspace_admin_required": True,
            "minimum_expiry_days": authority.MIN_THIRD_PARTY_GRANT_DAYS,
            "maximum_expiry_days": authority.MAX_THIRD_PARTY_GRANT_DAYS,
        },
        "integrations": {
            "github_actions": "external integration; existing workflows remain unchanged",
            "ollama": "external model integration; existing configuration remains unchanged",
        },
    }


@router.get("/action/manifest")
def action_manifest() -> dict[str, Any]:
    """Expose the Amosclaud-native Action identity, not a GitHub workflow."""

    return {
        "name": "Amosclaud Action",
        "owner": "Amosclaud",
        "credential_type": "action",
        "scope": "action:run",
        "verification": "/api/v1/amosclaud/authority/verify",
        "execution": "delegates to the existing governed Amosclaud product surfaces",
        "tools": amosclaud_action.catalog(),
        "github_actions_changed": False,
    }


@router.get("/action/tools")
def action_tools(required_scope: str | None = Query(default=None)) -> dict[str, Any]:
    if required_scope and required_scope not in authority.PLATFORM_SCOPES:
        raise HTTPException(status_code=422, detail="Unknown authority scope")
    tools = amosclaud_action.catalog(required_scope=required_scope)
    return {
        "action": "Amosclaud Action",
        "tools": tools,
        "count": len(tools),
    }


@router.get("/action/authorize")
def authorize_action_tool(
    request: Request,
    tool: str = Query(..., min_length=1, max_length=100),
    workspace_id: str | None = Query(default=None),
) -> dict[str, Any]:
    raw = _raw_credential(request)
    principal = authority.verify_credential(raw, workspace_id=workspace_id)
    if principal is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid, revoked, expired, or workspace-mismatched credential",
        )
    authorization = amosclaud_action.authorize_tool(principal, tool)
    if authorization is None:
        raise HTTPException(status_code=404, detail="Amosclaud Action tool was not found")
    if not authorization["authorized"]:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "scope_not_granted",
                "tool": tool,
                "required_scope": authorization["required_scope"],
                "scopes": principal["scopes"],
            },
        )
    return {
        "authorized": True,
        "tool": authorization,
        "credential_type": principal["credential_type"],
        "expires_at": principal["expires_at"],
    }


@router.get("/model/manifest")
def model_manifest() -> dict[str, Any]:
    return {
        "name": "Amosclaud Model",
        "owner": "Amosclaud",
        "scope": "model:invoke",
        "credential_types": ["api_key", "token", "action"],
        "ollama_changed": False,
    }


@router.get("/credentials")
def list_credentials(
    include_revoked: bool = Query(default=False),
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    owner_id = None if bool(user["is_admin"]) else int(user["id"])
    return {
        "credentials": authority.list_platform_credentials(
            owner_user_id=owner_id,
            include_revoked=include_revoked,
        ),
        "expiration_policy": "manual_revocation",
    }


@router.post("/credentials", status_code=201)
def create_credential(
    body: PlatformCredentialCreate,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    try:
        return authority.issue_platform_credential(
            owner_user_id=int(user["id"]),
            name=body.name,
            credential_type=body.type,
            scopes=body.scopes,
            actor_user_id=int(user["id"]),
            is_admin=bool(user["is_admin"]),
        )
    except authority.AuthorityError as exc:
        raise _authority_error(exc) from exc


@router.post("/credentials/{credential_id}/rotate", status_code=201)
def rotate_credential(
    credential_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    try:
        return authority.rotate_platform_credential(
            credential_id,
            actor_user_id=int(user["id"]),
            is_admin=bool(user["is_admin"]),
        )
    except authority.AuthorityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/credentials/{credential_id}", status_code=204)
def revoke_credential(
    credential_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> None:
    try:
        authority.revoke_platform_credential(
            credential_id,
            actor_user_id=int(user["id"]),
            is_admin=bool(user["is_admin"]),
        )
    except authority.AuthorityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/workspaces/{workspace_id}/third-party-grants")
def list_third_party_grants(
    workspace_id: str,
    include_revoked: bool = Query(default=False),
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    _workspace_admin(workspace_id, user)
    try:
        grants = authority.list_workspace_grants(
            workspace_id,
            include_revoked=include_revoked,
        )
    except authority.AuthorityError as exc:
        raise _authority_error(exc) from exc
    return {
        "workspace_id": workspace_id,
        "grants": grants,
        "minimum_expiry_days": authority.MIN_THIRD_PARTY_GRANT_DAYS,
    }


@router.post("/workspaces/{workspace_id}/third-party-grants", status_code=201)
def create_third_party_grant(
    workspace_id: str,
    body: WorkspaceGrantCreate,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    _workspace_admin(workspace_id, user)
    try:
        return authority.issue_workspace_grant(
            workspace_id=workspace_id,
            provider=body.provider,
            subject=body.subject,
            scopes=body.scopes,
            expires_in_days=body.expires_in_days,
            created_by_user_id=int(user["id"]),
            actor_user_id=int(user["id"]),
        )
    except authority.AuthorityError as exc:
        raise _authority_error(exc) from exc


@router.post(
    "/workspaces/{workspace_id}/third-party-grants/{grant_id}/rotate",
    status_code=201,
)
def rotate_third_party_grant(
    workspace_id: str,
    grant_id: int,
    body: WorkspaceGrantRotate,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    _workspace_admin(workspace_id, user)
    try:
        replacement = authority.rotate_workspace_grant(
            grant_id,
            workspace_id=workspace_id,
            expires_in_days=body.expires_in_days,
            actor_user_id=int(user["id"]),
        )
    except authority.AuthorityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if replacement["workspace_id"] != workspace_id:
        raise HTTPException(status_code=404, detail="Workspace grant was not found")
    return replacement


@router.delete(
    "/workspaces/{workspace_id}/third-party-grants/{grant_id}",
    status_code=204,
)
def revoke_third_party_grant(
    workspace_id: str,
    grant_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> None:
    _workspace_admin(workspace_id, user)
    try:
        grants = authority.list_workspace_grants(workspace_id, include_revoked=True)
        if not any(int(item["id"]) == int(grant_id) for item in grants):
            raise authority.CredentialNotFound("Workspace grant was not found")
        authority.revoke_workspace_grant(
            grant_id,
            actor_user_id=int(user["id"]),
        )
    except authority.AuthorityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/verify")
def verify_authority_credential(
    request: Request,
    required_scope: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
) -> dict[str, Any]:
    if required_scope and required_scope not in authority.PLATFORM_SCOPES:
        raise HTTPException(status_code=422, detail="Unknown authority scope")
    raw = _raw_credential(request)
    principal = authority.verify_credential(
        raw,
        required_scope=required_scope,
        workspace_id=workspace_id,
    )
    if principal is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid, revoked, expired, or workspace-mismatched credential",
        )
    if not principal["scope_granted"]:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "scope_not_granted",
                "required_scope": required_scope,
                "scopes": principal["scopes"],
            },
        )
    return principal


__all__ = ["router"]
