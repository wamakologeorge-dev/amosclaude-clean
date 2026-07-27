"""Generic plugin, MCP, and feature-flag control-plane routes.

These routes are mounted by the built-in control-plane plugin, not hardcoded into
the primary application route list.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from amoscloud_ai import feature_flags, mcp_manager
from amoscloud_ai.api.routes import admin, task_router

router = APIRouter(tags=["plugins", "mcp", "feature-flags"])


class FlagUpsert(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=2_000)
    enabled: bool = False
    rollout_percentage: int = Field(default=0, ge=0, le=100)
    required_tiers: list[str] = Field(default_factory=list, max_length=20)
    owner_plugin: str = Field(default="admin", min_length=2, max_length=120)


class FlagTargetCreate(BaseModel):
    target_type: Literal["user", "workspace", "tier"]
    target_value: str = Field(min_length=1, max_length=300)
    enabled: bool


class MCPServerUpsert(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=2_000)
    endpoint: str = Field(min_length=8, max_length=2_000)
    auth_header_name: str | None = Field(default=None, max_length=120)
    auth_secret_env: str | None = Field(default=None, max_length=120)
    enabled: bool = False
    feature_flag_key: str = Field(default="mcp.integrations", min_length=3, max_length=120)
    allowed_tools: list[str] = Field(default_factory=list, max_length=500)
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class MCPScopeCreate(BaseModel):
    scope_type: Literal["user", "workspace", "tier"]
    scope_value: str = Field(min_length=1, max_length=300)


class MCPToolCall(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)
    workspace_id: str | None = Field(default=None, max_length=300)


def _user_id(session: str | None, authorization: str | None) -> int:
    return task_router._actor(session, authorization)


def _registry(_request: Request):
    from amoscloud_ai.extensions.runtime import get_registry

    try:
        return get_registry()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/registry")
def plugins(
    request: Request,
    administrator: sqlite3.Row = Depends(admin._admin_user),
) -> dict[str, Any]:
    del administrator
    registry = _registry(request)
    return {
        "entry_point_group": "amosclaud.plugins",
        "drop_in_package": "amoscloud_ai.plugins",
        "plugins": registry.list_plugins(),
        "agent_tools": sorted(registry.agent_tools),
        "terminal_commands": sorted(registry.terminal_commands),
        "mcp_server_factories": sorted(registry.mcp_server_factories),
    }


@router.get("/registry/health")
def plugin_health(
    request: Request,
    administrator: sqlite3.Row = Depends(admin._admin_user),
) -> list[dict[str, Any]]:
    del administrator
    return _registry(request).run_health_checks()


@router.get("/flags")
def flags(
    administrator: sqlite3.Row = Depends(admin._admin_user),
) -> list[dict[str, Any]]:
    del administrator
    return feature_flags.list_flags()


@router.put("/flags/{key}")
def put_flag(
    key: str,
    body: FlagUpsert,
    administrator: sqlite3.Row = Depends(admin._admin_user),
) -> dict[str, Any]:
    try:
        return feature_flags.upsert_flag(
            key=key,
            name=body.name,
            description=body.description,
            enabled=body.enabled,
            rollout_percentage=body.rollout_percentage,
            required_tiers=body.required_tiers,
            owner_plugin=body.owner_plugin,
            actor_user_id=int(administrator["id"]),
        )
    except feature_flags.FeatureFlagError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/flags/{key}/targets", status_code=201)
def add_flag_target(
    key: str,
    body: FlagTargetCreate,
    administrator: sqlite3.Row = Depends(admin._admin_user),
) -> dict[str, Any]:
    try:
        return feature_flags.set_target(
            key=key,
            target_type=body.target_type,
            target_value=body.target_value,
            enabled=body.enabled,
            actor_user_id=int(administrator["id"]),
        )
    except feature_flags.FeatureFlagError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/flags/targets/{target_id}", status_code=204)
def remove_flag_target(
    target_id: int,
    administrator: sqlite3.Row = Depends(admin._admin_user),
) -> None:
    try:
        feature_flags.delete_target(target_id, actor_user_id=int(administrator["id"]))
    except feature_flags.FeatureFlagError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/features")
def evaluate_all_features(
    workspace_id: str | None = Query(default=None, max_length=300),
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    user_id = _user_id(amos_session, authorization)
    return [
        feature_flags.evaluate(
            item["key"],
            user_id=user_id,
            workspace_id=workspace_id,
        )
        for item in feature_flags.list_flags()
    ]


@router.get("/features/{key}")
def evaluate_feature(
    key: str,
    workspace_id: str | None = Query(default=None, max_length=300),
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    user_id = _user_id(amos_session, authorization)
    try:
        return feature_flags.evaluate(key, user_id=user_id, workspace_id=workspace_id)
    except feature_flags.FeatureFlagError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/mcp/servers/admin")
def admin_mcp_servers(
    administrator: sqlite3.Row = Depends(admin._admin_user),
) -> list[dict[str, Any]]:
    del administrator
    return mcp_manager.list_servers()


@router.put("/mcp/servers/{server_id}")
def put_mcp_server(
    server_id: str,
    body: MCPServerUpsert,
    administrator: sqlite3.Row = Depends(admin._admin_user),
) -> dict[str, Any]:
    try:
        return mcp_manager.upsert_server(
            server_id=server_id,
            name=body.name,
            description=body.description,
            endpoint=body.endpoint,
            auth_header_name=body.auth_header_name,
            auth_secret_env=body.auth_secret_env,
            enabled=body.enabled,
            feature_flag_key=body.feature_flag_key,
            allowed_tools=body.allowed_tools,
            timeout_seconds=body.timeout_seconds,
            created_by=int(administrator["id"]),
        )
    except (mcp_manager.MCPManagerError, feature_flags.FeatureFlagError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/mcp/servers/{server_id}/scopes", status_code=201)
def add_mcp_scope(
    server_id: str,
    body: MCPScopeCreate,
    administrator: sqlite3.Row = Depends(admin._admin_user),
) -> dict[str, Any]:
    del administrator
    try:
        return mcp_manager.set_scope(server_id, body.scope_type, body.scope_value)
    except mcp_manager.MCPManagerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/mcp/scopes/{scope_id}", status_code=204)
def remove_mcp_scope(
    scope_id: int,
    administrator: sqlite3.Row = Depends(admin._admin_user),
) -> None:
    del administrator
    try:
        mcp_manager.delete_scope(scope_id)
    except mcp_manager.MCPManagerError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/mcp/servers/{server_id}/probe")
async def probe_mcp_server(
    server_id: str,
    administrator: sqlite3.Row = Depends(admin._admin_user),
) -> dict[str, Any]:
    del administrator
    try:
        return await mcp_manager.probe_server(server_id)
    except mcp_manager.MCPManagerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/mcp/servers")
def available_mcp_servers(
    workspace_id: str | None = Query(default=None, max_length=300),
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    user_id = _user_id(amos_session, authorization)
    available = []
    for server in mcp_manager.list_servers(include_scopes=False):
        try:
            mcp_manager.authorized_server(
                server["id"],
                user_id=user_id,
                workspace_id=workspace_id,
            )
        except mcp_manager.MCPManagerError:
            continue
        available.append(
            {
                key: server.get(key)
                for key in (
                    "id",
                    "name",
                    "description",
                    "feature_flag_key",
                    "last_probe_at",
                    "last_probe_status",
                    "last_probe_detail",
                )
            }
        )
    return available


@router.get("/mcp/servers/{server_id}/tools")
async def mcp_tools(
    server_id: str,
    workspace_id: str | None = Query(default=None, max_length=300),
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    user_id = _user_id(amos_session, authorization)
    try:
        return await mcp_manager.list_tools(
            server_id,
            user_id=user_id,
            workspace_id=workspace_id,
        )
    except mcp_manager.MCPManagerError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"MCP tools/list failed safely: {type(exc).__name__}",
        ) from exc


@router.post("/mcp/servers/{server_id}/tools/{tool_name:path}")
async def invoke_mcp_tool(
    server_id: str,
    tool_name: str,
    body: MCPToolCall,
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    user_id = _user_id(amos_session, authorization)
    try:
        return await mcp_manager.call_tool(
            server_id,
            tool_name,
            body.arguments,
            user_id=user_id,
            workspace_id=body.workspace_id,
        )
    except mcp_manager.MCPManagerError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"MCP tool call failed safely: {type(exc).__name__}",
        ) from exc
