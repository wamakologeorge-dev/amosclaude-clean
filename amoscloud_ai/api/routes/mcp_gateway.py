"""Bearer-authenticated Amosclaud API surface used by first-party MCP clients.

This module is deliberately provider-neutral.  ChatGPT, VS Code, a physical
Amosclaud computer, or another authorized MCP client can call the same Amosclaud
repository primitives without receiving direct GitHub credentials.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from amoscloud_ai.api.routes import auth, repositories
from amoscloud_ai.organization_support import bearer_identity

router = APIRouter(prefix="/mcp-gateway", tags=["amosclaud-mcp-gateway"])


@dataclass(frozen=True)
class MCPPrincipal:
    """Resolved Amosclaud account and credential policy for one MCP request."""

    user: sqlite3.Row
    identity: dict[str, Any]


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "").strip()
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        raise HTTPException(
            status_code=401,
            detail="Provide a valid Amosclaud bearer credential",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return value.strip()


def _resolve_user(identity: dict[str, Any]) -> sqlite3.Row:
    """Resolve an API principal to the normal Amosclaud user record.

    The protected owner key intentionally resolves to user_id=0 in the generic
    support-time gateway.  For repository ownership we bind that owner identity
    to the first active Amosclaud administrator account instead of inventing a
    synthetic repository owner.
    """

    user_id = int(identity.get("user_id") or 0)
    with auth._connect() as db:
        if user_id > 0:
            user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        elif bool(identity.get("is_admin")):
            user = db.execute(
                "SELECT * FROM users WHERE is_admin = 1 ORDER BY id ASC LIMIT 1"
            ).fetchone()
        else:
            user = None
    if user is None:
        raise HTTPException(status_code=401, detail="Amosclaud account for this key was not found")
    return user


def _principal(request: Request) -> MCPPrincipal:
    identity = bearer_identity(_bearer_token(request))
    if identity is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or revoked Amosclaud credential",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return MCPPrincipal(user=_resolve_user(identity), identity=identity)


def _require_scope(principal: MCPPrincipal, scope: str) -> None:
    """Enforce scopes for first-party scoped credentials.

    Legacy Autonomous/provider keys predate scoped authority credentials and
    therefore keep their existing account-level behavior.  Scoped Amosclaud
    tokens are denied unless the exact repository scope (or authority:admin) is
    present.
    """

    if bool(principal.identity.get("is_admin")):
        return
    raw_scopes = principal.identity.get("scopes")
    if raw_scopes is None:
        return
    scopes = {str(item).strip() for item in raw_scopes if str(item).strip()}
    if scope not in scopes and "authority:admin" not in scopes:
        raise HTTPException(status_code=403, detail=f"Amosclaud credential requires {scope}")


def _repository_payload(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value


@router.get("/identity")
def mcp_identity(principal: MCPPrincipal = Depends(_principal)) -> dict[str, Any]:
    """Return safe identity metadata so an MCP client can prove its connection."""

    scopes = principal.identity.get("scopes")
    return {
        "connected": True,
        "provider": "amosclaud",
        "user_id": int(principal.user["id"]),
        "name": principal.user["name"],
        "email": principal.user["email"],
        "administrator": bool(principal.user["is_admin"]),
        "credential_type": principal.identity.get("key_type", "amosclaud"),
        "scopes": sorted(str(item) for item in scopes) if scopes is not None else None,
    }


@router.get("/repositories")
def list_mcp_repositories(principal: MCPPrincipal = Depends(_principal)) -> list[dict[str, Any]]:
    """List repositories visible to the authenticated Amosclaud account."""

    _require_scope(principal, "repository:read")
    return [
        _repository_payload(item)
        for item in repositories.list_repositories(user=principal.user)
    ]


@router.post("/repositories", status_code=201)
def create_mcp_repository(
    body: repositories.RepositoryCreate,
    principal: MCPPrincipal = Depends(_principal),
) -> dict[str, Any]:
    """Create a native Amosclaud repository owned by the authenticated account."""

    _require_scope(principal, "repository:write")
    return _repository_payload(repositories.create_repository(body=body, user=principal.user))


@router.get("/repositories/{repository_id}")
def get_mcp_repository(
    repository_id: int,
    principal: MCPPrincipal = Depends(_principal),
) -> dict[str, Any]:
    """Read one native Amosclaud repository record."""

    _require_scope(principal, "repository:read")
    return _repository_payload(
        repositories.get_repository(repository_id=repository_id, user=principal.user)
    )


@router.get("/repositories/{repository_id}/tree")
def list_mcp_repository_tree(
    repository_id: int,
    branch: str = Query("main"),
    principal: MCPPrincipal = Depends(_principal),
) -> list[dict[str, Any]]:
    """List files and directories from a native Amosclaud repository branch."""

    _require_scope(principal, "repository:read")
    return repositories.list_tree(
        repository_id=repository_id,
        branch=branch,
        user=principal.user,
    )


@router.get("/repositories/{repository_id}/files")
def read_mcp_repository_file(
    repository_id: int,
    path: str,
    branch: str = Query("main"),
    principal: MCPPrincipal = Depends(_principal),
) -> dict[str, Any]:
    """Read one UTF-8 file from a native Amosclaud repository."""

    _require_scope(principal, "repository:read")
    return repositories.read_file(
        repository_id=repository_id,
        path=path,
        branch=branch,
        user=principal.user,
    )


@router.put("/repositories/{repository_id}/files")
def write_mcp_repository_file(
    repository_id: int,
    body: repositories.FileWriteRequest,
    principal: MCPPrincipal = Depends(_principal),
) -> dict[str, Any]:
    """Create or replace a file and commit the change in Amosclaud."""

    _require_scope(principal, "repository:write")
    return repositories.write_file(
        repository_id=repository_id,
        body=body,
        user=principal.user,
    )


@router.delete("/repositories/{repository_id}/files")
def delete_mcp_repository_file(
    repository_id: int,
    body: repositories.FileDeleteRequest,
    principal: MCPPrincipal = Depends(_principal),
) -> dict[str, Any]:
    """Delete a file or folder and commit the change in Amosclaud."""

    _require_scope(principal, "repository:write")
    return repositories.delete_file(
        repository_id=repository_id,
        body=body,
        user=principal.user,
    )


@router.get("/repositories/{repository_id}/branches")
def list_mcp_repository_branches(
    repository_id: int,
    principal: MCPPrincipal = Depends(_principal),
) -> list[str]:
    """List native Amosclaud branches for one repository."""

    _require_scope(principal, "repository:read")
    return repositories.list_branches(repository_id=repository_id, user=principal.user)


@router.post("/repositories/{repository_id}/branches", status_code=201)
def create_mcp_repository_branch(
    repository_id: int,
    body: repositories.BranchCreateRequest,
    principal: MCPPrincipal = Depends(_principal),
) -> dict[str, Any]:
    """Create a branch inside the native Amosclaud repository provider."""

    _require_scope(principal, "repository:write")
    return repositories.create_branch(
        repository_id=repository_id,
        body=body,
        user=principal.user,
    )


@router.get("/repositories/{repository_id}/commits")
def list_mcp_repository_commits(
    repository_id: int,
    branch: str = Query("main"),
    limit: int = Query(50, ge=1, le=100),
    principal: MCPPrincipal = Depends(_principal),
) -> list[dict[str, Any]]:
    """List real commit history from an Amosclaud repository branch."""

    _require_scope(principal, "repository:read")
    return repositories.list_commits(
        repository_id=repository_id,
        branch=branch,
        limit=limit,
        user=principal.user,
    )
