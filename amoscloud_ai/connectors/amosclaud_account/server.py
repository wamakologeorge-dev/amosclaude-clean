"""Full read/write MCP server for one authenticated Amosclaud account."""

from __future__ import annotations

from typing import Any

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl

from amoscloud_ai.api.routes import auth

from .gateway import ConnectorGatewayError, request_as_user, required_scope
from .oauth import (
    AmosclaudConnectorTokenVerifier,
    connector_resource_url,
    oauth_issuer_url,
)

READ_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
WRITE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=True,
)

mcp = FastMCP(
    "Amosclaud Account",
    instructions=(
        "Use this connector as the authenticated control plane for the user's Amosclaud "
        "account. Read current platform evidence before changing anything. You may use "
        "write tools to repair, create, update, deploy, or remove Amosclaud resources "
        "within the connected account's scopes. Never claim success unless the returned "
        "Amosclaud response, pipeline, tests, logs, branch, commit, or deployment evidence "
        "proves it. Repository changes must use bounded branches; do not force-push, "
        "rebase published work, or write directly to a protected default branch."
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    token_verifier=AmosclaudConnectorTokenVerifier(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(oauth_issuer_url()),
        resource_server_url=AnyHttpUrl(connector_resource_url()),
        required_scopes=["account:read"],
    ),
)


def _access_token(ctx: Context) -> Any:
    request_context = getattr(ctx, "request_context", None)
    request = getattr(request_context, "request", None)
    user = getattr(request, "user", None)
    token = getattr(user, "access_token", None)
    if token is not None:
        return token

    # v1.x FastMCP exposes a context-local accessor. Stateless HTTP is used, so
    # the access token cannot leak between sessions while older SDK versions run.
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token

        token = get_access_token()
    except (ImportError, LookupError):
        token = None
    if token is None:
        raise RuntimeError("Amosclaud connector authentication context is unavailable")
    return token


def _identity(ctx: Context) -> tuple[int, set[str], dict[str, Any]]:
    token = _access_token(ctx)
    subject = str(getattr(token, "subject", "") or "").strip()
    if not subject.isdigit() or int(subject) <= 0:
        raise RuntimeError("Amosclaud connector token has no valid account subject")
    scopes = {str(scope) for scope in (getattr(token, "scopes", None) or [])}
    claims = dict(getattr(token, "claims", None) or {})
    return int(subject), scopes, claims


def _require(ctx: Context, scope: str) -> tuple[int, dict[str, Any]]:
    user_id, scopes, claims = _identity(ctx)
    if scope not in scopes:
        raise RuntimeError(f"Connected Amosclaud account token requires scope: {scope}")
    if scope == "admin:write" and not bool(claims.get("is_admin")):
        raise RuntimeError("This Amosclaud account is not an administrator")
    return user_id, claims


def _require_all(ctx: Context, required: set[str]) -> tuple[int, dict[str, Any]]:
    user_id, scopes, claims = _identity(ctx)
    missing = sorted(required - scopes)
    if missing:
        raise RuntimeError(
            "Connected Amosclaud account token requires scopes: " + ", ".join(missing)
        )
    if "admin:write" in required and not bool(claims.get("is_admin")):
        raise RuntimeError("This Amosclaud account is not an administrator")
    return user_id, claims


def _account_row(user_id: int) -> dict[str, Any]:
    with auth._connect() as db:
        row = db.execute(
            "SELECT id,name,email,is_admin,provider,created_at FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
    if not row:
        raise RuntimeError("The connected Amosclaud account no longer exists")
    return {
        "id": int(row["id"]),
        "name": str(row["name"]),
        "email": str(row["email"]),
        "is_admin": bool(row["is_admin"]),
        "provider": str(row["provider"]),
        "created_at": str(row["created_at"]),
    }


@mcp.tool(annotations=READ_ANNOTATIONS)
def amosclaud_account(ctx: Context) -> dict[str, Any]:
    """Return the authenticated Amosclaud account and granted connector scopes."""

    user_id, scopes, claims = _identity(ctx)
    return {
        "account": _account_row(user_id),
        "connector": {
            "resource": connector_resource_url(),
            "issuer": oauth_issuer_url(),
            "scopes": sorted(scopes),
            "client_id": str(getattr(_access_token(ctx), "client_id", "")),
            "claims": {
                "is_admin": bool(claims.get("is_admin")),
            },
        },
    }


@mcp.tool(annotations=READ_ANNOTATIONS)
async def amosclaud_read(
    path: str,
    ctx: Context,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read any authorized Amosclaud API resource.

    Use an `/api/v1/...` path, `/health`, `/ready`, `/openapi.json`, or
    `/openapi.yaml`. The connector executes as the connected Amosclaud account.
    """

    scope = required_scope("GET", path)
    user_id, _ = _require(ctx, scope)
    try:
        return await request_as_user(
            user_id=user_id,
            method="GET",
            path=path,
            query=query,
        )
    except ConnectorGatewayError as exc:
        raise RuntimeError(str(exc)) from exc


@mcp.tool(annotations=WRITE_ANNOTATIONS)
async def amosclaud_write(
    method: str,
    path: str,
    ctx: Context,
    body: dict[str, Any] | list[Any] | None = None,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create, update, repair, deploy, or remove an Amosclaud resource.

    `method` must be POST, PUT, PATCH, or DELETE and `path` must start with
    `/api/v1/`. The connector uses the connected account and its granted scopes.
    """

    normalized_method = method.upper()
    scope = required_scope(normalized_method, path)
    user_id, _ = _require(ctx, scope)
    try:
        return await request_as_user(
            user_id=user_id,
            method=normalized_method,
            path=path,
            query=query,
            body=body,
        )
    except ConnectorGatewayError as exc:
        raise RuntimeError(str(exc)) from exc


@mcp.tool(annotations=WRITE_ANNOTATIONS)
async def amosclaud_run_autonomous(
    objective: str,
    ctx: Context,
    repository_id: int | None = None,
    branch: str = "main",
    mode: str = "fix",
    apply_changes: bool = True,
) -> dict[str, Any]:
    """Start real Amosclaud Autonomous work for the connected account.

    Modes: autonomous-check, build, fix, deploy, or monitor. Write-capable work
    remains governed by Amosclaud repository isolation, verification, and branch
    protection. The returned pipeline ID is the source of truth.
    """

    required = {"tasks:write"}
    if repository_id is not None and apply_changes:
        required.add("repositories:write")
    if mode.strip().lower() == "deploy":
        required.add("deployments:write")
    user_id, _ = _require_all(ctx, required)
    cleaned_objective = objective.strip()
    if not cleaned_objective:
        raise RuntimeError("objective cannot be empty")
    normalized_mode = mode.strip().lower()
    allowed_modes = {"autonomous-check", "build", "fix", "deploy", "monitor"}
    if normalized_mode not in allowed_modes:
        raise RuntimeError(f"mode must be one of: {', '.join(sorted(allowed_modes))}")
    metadata: dict[str, Any] = {
        "source": "amosclaud-account-connector",
        "connector_resource": connector_resource_url(),
        "use_agent": True,
        "apply_changes": bool(apply_changes),
    }
    if repository_id is not None:
        if repository_id <= 0:
            raise RuntimeError("repository_id must be a positive integer")
        metadata["repository_id"] = repository_id
    return await request_as_user(
        user_id=user_id,
        method="POST",
        path="/api/v1/agent/run",
        body={
            "mode": normalized_mode,
            "objective": cleaned_objective,
            "branch": branch.strip() or "main",
            "metadata": metadata,
        },
    )


@mcp.tool(annotations=READ_ANNOTATIONS)
async def amosclaud_pipeline(
    pipeline_id: str,
    ctx: Context,
) -> dict[str, Any]:
    """Read the status, jobs, logs, and evidence for an Amosclaud pipeline."""

    user_id, _ = _require(ctx, "tasks:read")
    cleaned = pipeline_id.strip()
    if not cleaned:
        raise RuntimeError("pipeline_id cannot be empty")
    return await request_as_user(
        user_id=user_id,
        method="GET",
        path=f"/api/v1/pipelines/{cleaned}",
    )


@mcp.resource("amosclaud-account://me")
def account_resource(ctx: Context) -> dict[str, Any]:
    """Authenticated Amosclaud account identity."""

    user_id, _, _ = _identity(ctx)
    return _account_row(user_id)
