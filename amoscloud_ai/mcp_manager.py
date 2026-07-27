"""Universal Model Context Protocol client manager for Amosclaud.

The manager stores server metadata and environment-variable references, never raw
credentials. It uses the official MCP Python SDK Streamable HTTP client and
checks feature flags, account/workspace scopes, endpoint policy, and tool
allowlists before any remote call.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import socket
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from amoscloud_ai import feature_flags
from amoscloud_ai.api.routes import auth

_SERVER_ID = re.compile(r"^[a-z][a-z0-9_.-]{2,119}$")
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,119}$")
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_.:/-]{1,200}$")


class MCPManagerError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def connect() -> sqlite3.Connection:
    db = auth._connect()
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def ensure_schema(db: sqlite3.Connection, *, commit: bool = True) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS mcp_servers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            endpoint TEXT NOT NULL,
            auth_header_name TEXT,
            auth_secret_env TEXT,
            enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
            feature_flag_key TEXT NOT NULL DEFAULT 'mcp.integrations',
            allowed_tools_json TEXT NOT NULL DEFAULT '[]',
            timeout_seconds INTEGER NOT NULL DEFAULT 30 CHECK(timeout_seconds BETWEEN 1 AND 300),
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_probe_at TEXT,
            last_probe_status TEXT,
            last_probe_detail TEXT,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE RESTRICT
        );

        CREATE TABLE IF NOT EXISTS mcp_server_scopes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id TEXT NOT NULL,
            scope_type TEXT NOT NULL CHECK(scope_type IN ('user','workspace','tier')),
            scope_value TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(server_id,scope_type,scope_value),
            FOREIGN KEY(server_id) REFERENCES mcp_servers(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_mcp_server_scopes_lookup
            ON mcp_server_scopes(server_id,scope_type,scope_value);

        CREATE TABLE IF NOT EXISTS mcp_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id TEXT NOT NULL,
            user_id INTEGER,
            workspace_id TEXT,
            action TEXT NOT NULL,
            tool_name TEXT,
            status TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY(server_id) REFERENCES mcp_servers(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_mcp_audit_server_time
            ON mcp_audit_log(server_id,created_at DESC);
        """
    )
    if commit:
        db.commit()


def validate_server_id(value: str) -> str:
    server_id = str(value or "").strip().lower()
    if not _SERVER_ID.fullmatch(server_id):
        raise MCPManagerError("MCP server IDs must use lowercase letters, numbers, dots, dashes, or underscores")
    return server_id


def _allow_private_endpoints() -> bool:
    return os.getenv("AMOSCLAUD_MCP_ALLOW_PRIVATE_ENDPOINTS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _blocked_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return bool(
        ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or ip.is_private
    )


def validate_endpoint(value: str, *, resolve_dns: bool = True) -> str:
    endpoint = str(value or "").strip().rstrip("/")
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise MCPManagerError("MCP endpoints must use HTTP or HTTPS")
    if parsed.username or parsed.password or parsed.fragment:
        raise MCPManagerError("MCP endpoints must not contain credentials or fragments")
    allow_private = _allow_private_endpoints()
    if parsed.scheme != "https" and not allow_private:
        raise MCPManagerError("Public MCP endpoints must use HTTPS")
    if resolve_dns:
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
            }
        except socket.gaierror as exc:
            raise MCPManagerError("MCP endpoint hostname could not be resolved") from exc
        if not allow_private and any(_blocked_ip(address) for address in addresses):
            raise MCPManagerError("MCP endpoint resolved to a private or special network address")
    return endpoint


def _headers(row: sqlite3.Row) -> dict[str, str]:
    name = str(row["auth_header_name"] or "").strip()
    secret_env = str(row["auth_secret_env"] or "").strip()
    if not name and not secret_env:
        return {}
    if not name or not secret_env:
        raise MCPManagerError("MCP authentication requires both a header name and a secret environment variable")
    if not _ENV_NAME.fullmatch(secret_env):
        raise MCPManagerError("MCP secret environment-variable name is invalid")
    value = os.getenv(secret_env, "").strip()
    if not value:
        raise MCPManagerError(f"MCP credential environment variable {secret_env} is not configured")
    if "\r" in name or "\n" in name or "\r" in value or "\n" in value:
        raise MCPManagerError("MCP authentication header contains an invalid newline")
    return {name: value}


def _server_dict(row: sqlite3.Row, *, include_scopes: bool = False, db: sqlite3.Connection | None = None) -> dict[str, Any]:
    item = dict(row)
    item["enabled"] = bool(item["enabled"])
    item["allowed_tools"] = _loads(item.pop("allowed_tools_json"), [])
    item["credential_configured"] = bool(
        item.get("auth_secret_env") and os.getenv(str(item["auth_secret_env"]), "").strip()
    )
    if include_scopes:
        if db is None:
            raise RuntimeError("A database connection is required to include MCP scopes")
        item["scopes"] = [
            {
                "id": scope["id"],
                "scope_type": scope["scope_type"],
                "scope_value": scope["scope_value"],
                "created_at": scope["created_at"],
            }
            for scope in db.execute(
                "SELECT * FROM mcp_server_scopes WHERE server_id=? ORDER BY scope_type,scope_value",
                (row["id"],),
            ).fetchall()
        ]
    return item


def upsert_server(
    *,
    server_id: str,
    name: str,
    description: str,
    endpoint: str,
    auth_header_name: str | None,
    auth_secret_env: str | None,
    enabled: bool,
    feature_flag_key: str,
    allowed_tools: list[str],
    timeout_seconds: int,
    created_by: int,
) -> dict[str, Any]:
    sid = validate_server_id(server_id)
    safe_endpoint = validate_endpoint(endpoint, resolve_dns=False)
    header_name = str(auth_header_name or "").strip() or None
    secret_env = str(auth_secret_env or "").strip() or None
    if bool(header_name) != bool(secret_env):
        raise MCPManagerError("Set both auth_header_name and auth_secret_env, or neither")
    if secret_env and not _ENV_NAME.fullmatch(secret_env):
        raise MCPManagerError("MCP secret environment-variable name is invalid")
    tools = sorted({str(tool).strip() for tool in allowed_tools if str(tool).strip()})
    if any(not _TOOL_NAME.fullmatch(tool) for tool in tools):
        raise MCPManagerError("One or more MCP tool allowlist names are invalid")
    flag_key = feature_flags.validate_key(feature_flag_key)
    now = _now()
    with connect() as db:
        ensure_schema(db, commit=False)
        db.execute(
            """INSERT INTO mcp_servers(
                   id,name,description,endpoint,auth_header_name,auth_secret_env,
                   enabled,feature_flag_key,allowed_tools_json,timeout_seconds,
                   created_by,created_at,updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                   name=excluded.name,
                   description=excluded.description,
                   endpoint=excluded.endpoint,
                   auth_header_name=excluded.auth_header_name,
                   auth_secret_env=excluded.auth_secret_env,
                   enabled=excluded.enabled,
                   feature_flag_key=excluded.feature_flag_key,
                   allowed_tools_json=excluded.allowed_tools_json,
                   timeout_seconds=excluded.timeout_seconds,
                   updated_at=excluded.updated_at""",
            (
                sid,
                name.strip()[:160] or sid,
                description.strip()[:2_000],
                safe_endpoint,
                header_name,
                secret_env,
                int(enabled),
                flag_key,
                _json(tools),
                max(1, min(int(timeout_seconds), 300)),
                created_by,
                now,
                now,
            ),
        )
        db.commit()
        row = db.execute("SELECT * FROM mcp_servers WHERE id=?", (sid,)).fetchone()
        return _server_dict(row, include_scopes=True, db=db)


def list_servers(*, include_scopes: bool = True) -> list[dict[str, Any]]:
    with connect() as db:
        ensure_schema(db)
        rows = db.execute("SELECT * FROM mcp_servers ORDER BY name,id").fetchall()
        return [_server_dict(row, include_scopes=include_scopes, db=db) for row in rows]


def set_scope(server_id: str, scope_type: str, scope_value: str) -> dict[str, Any]:
    sid = validate_server_id(server_id)
    target = scope_type.strip().lower()
    value = scope_value.strip()
    if target not in {"user", "workspace", "tier"}:
        raise MCPManagerError("MCP scope type must be user, workspace, or tier")
    if not value or len(value) > 300:
        raise MCPManagerError("MCP scope value is required")
    if target == "user" and not value.isdigit():
        raise MCPManagerError("MCP user scopes require a numeric Amosclaud user ID")
    with connect() as db:
        ensure_schema(db, commit=False)
        if not db.execute("SELECT 1 FROM mcp_servers WHERE id=?", (sid,)).fetchone():
            raise MCPManagerError("MCP server not found")
        now = _now()
        db.execute(
            """INSERT OR IGNORE INTO mcp_server_scopes(
                   server_id,scope_type,scope_value,created_at
               ) VALUES (?,?,?,?)""",
            (sid, target, value, now),
        )
        db.commit()
        row = db.execute(
            """SELECT * FROM mcp_server_scopes
               WHERE server_id=? AND scope_type=? AND scope_value=?""",
            (sid, target, value),
        ).fetchone()
    return dict(row)


def delete_scope(scope_id: int) -> None:
    with connect() as db:
        ensure_schema(db, commit=False)
        cursor = db.execute("DELETE FROM mcp_server_scopes WHERE id=?", (scope_id,))
        if not cursor.rowcount:
            raise MCPManagerError("MCP scope not found")
        db.commit()


def _scope_allowed(db: sqlite3.Connection, row: sqlite3.Row, user_id: int, workspace_id: str | None, tier: str) -> bool:
    scopes = db.execute(
        "SELECT scope_type,scope_value FROM mcp_server_scopes WHERE server_id=?",
        (row["id"],),
    ).fetchall()
    if not scopes:
        return True
    expected = {
        ("user", str(user_id)),
        ("tier", tier),
    }
    if workspace_id:
        expected.add(("workspace", workspace_id))
    return any((scope["scope_type"], scope["scope_value"]) in expected for scope in scopes)


def authorized_server(server_id: str, *, user_id: int, workspace_id: str | None = None) -> sqlite3.Row:
    sid = validate_server_id(server_id)
    with connect() as db:
        ensure_schema(db)
        row = db.execute("SELECT * FROM mcp_servers WHERE id=?", (sid,)).fetchone()
        if not row:
            raise MCPManagerError("MCP server not found")
        if not bool(row["enabled"]):
            raise MCPManagerError("MCP server is disabled")
        tier = feature_flags.current_tier(db, user_id)
        flag = feature_flags.evaluate(
            row["feature_flag_key"],
            user_id=user_id,
            workspace_id=workspace_id,
            tier=tier,
            db=db,
        )
        if not flag["enabled"]:
            raise MCPManagerError(
                f"MCP server is hidden by feature flag {row['feature_flag_key']}: {flag['reason']}"
            )
        if not _scope_allowed(db, row, user_id, workspace_id, tier):
            raise MCPManagerError("MCP server is not assigned to this user, workspace, or tier")
        return row


def _audit(
    server_id: str,
    *,
    user_id: int | None,
    workspace_id: str | None,
    action: str,
    tool_name: str | None,
    status: str,
    detail: str,
) -> None:
    with connect() as db:
        ensure_schema(db, commit=False)
        db.execute(
            """INSERT INTO mcp_audit_log(
                   server_id,user_id,workspace_id,action,tool_name,status,detail,created_at
               ) VALUES (?,?,?,?,?,?,?,?)""",
            (
                server_id,
                user_id,
                workspace_id,
                action,
                tool_name,
                status,
                detail[:2_000],
                _now(),
            ),
        )
        db.commit()


def _sdk() -> tuple[Any, Any]:
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except ImportError as exc:
        raise MCPManagerError(
            "The MCP Python SDK is not installed. Install the pinned mcp>=1.27,<2 dependency."
        ) from exc
    return ClientSession, streamable_http_client


def _serializable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serializable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


async def _session_call(row: sqlite3.Row, operation: str, *, tool_name: str | None = None, arguments: dict[str, Any] | None = None) -> Any:
    ClientSession, streamable_http_client = _sdk()
    endpoint = validate_endpoint(row["endpoint"], resolve_dns=True)
    timeout = float(row["timeout_seconds"])
    limits = httpx.Limits(max_connections=4, max_keepalive_connections=2)
    async with httpx.AsyncClient(
        headers=_headers(row),
        timeout=httpx.Timeout(timeout),
        follow_redirects=False,
        limits=limits,
    ) as client:
        async with streamable_http_client(endpoint, http_client=client) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await asyncio.wait_for(session.initialize(), timeout=timeout)
                if operation == "list_tools":
                    result = await asyncio.wait_for(session.list_tools(), timeout=timeout)
                elif operation == "call_tool" and tool_name:
                    result = await asyncio.wait_for(
                        session.call_tool(tool_name, arguments=arguments or {}),
                        timeout=timeout,
                    )
                else:
                    raise MCPManagerError("Unsupported MCP client operation")
                return _serializable(result)


async def list_tools(server_id: str, *, user_id: int, workspace_id: str | None = None) -> dict[str, Any]:
    row = authorized_server(server_id, user_id=user_id, workspace_id=workspace_id)
    try:
        payload = await _session_call(row, "list_tools")
        allowed = set(_loads(row["allowed_tools_json"], []))
        tools = payload.get("tools", []) if isinstance(payload, dict) else []
        if allowed:
            tools = [tool for tool in tools if str(tool.get("name")) in allowed]
        result = {"server_id": row["id"], "tools": tools}
        _audit(row["id"], user_id=user_id, workspace_id=workspace_id, action="list_tools", tool_name=None, status="success", detail=f"Returned {len(tools)} tool(s)")
        return result
    except Exception as exc:
        _audit(row["id"], user_id=user_id, workspace_id=workspace_id, action="list_tools", tool_name=None, status="failed", detail=f"{type(exc).__name__}: {exc}")
        raise


async def call_tool(
    server_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    user_id: int,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    row = authorized_server(server_id, user_id=user_id, workspace_id=workspace_id)
    tool = str(tool_name or "").strip()
    if not _TOOL_NAME.fullmatch(tool):
        raise MCPManagerError("MCP tool name is invalid")
    allowed = set(_loads(row["allowed_tools_json"], []))
    if allowed and tool not in allowed:
        raise MCPManagerError("MCP tool is not in the server allowlist")
    encoded = _json(arguments)
    if len(encoded.encode("utf-8")) > 256_000:
        raise MCPManagerError("MCP tool arguments exceed the 256 KiB limit")
    try:
        payload = await _session_call(row, "call_tool", tool_name=tool, arguments=arguments)
        _audit(row["id"], user_id=user_id, workspace_id=workspace_id, action="call_tool", tool_name=tool, status="success", detail="Remote MCP tool call completed")
        return {"server_id": row["id"], "tool_name": tool, "result": payload}
    except Exception as exc:
        _audit(row["id"], user_id=user_id, workspace_id=workspace_id, action="call_tool", tool_name=tool, status="failed", detail=f"{type(exc).__name__}: {exc}")
        raise


async def probe_server(server_id: str) -> dict[str, Any]:
    sid = validate_server_id(server_id)
    with connect() as db:
        ensure_schema(db)
        row = db.execute("SELECT * FROM mcp_servers WHERE id=?", (sid,)).fetchone()
        if not row:
            raise MCPManagerError("MCP server not found")
    try:
        payload = await _session_call(row, "list_tools")
        tools = payload.get("tools", []) if isinstance(payload, dict) else []
        status = "operational"
        detail = f"MCP initialize and tools/list succeeded ({len(tools)} tool(s))."
    except Exception as exc:
        status = "unreachable"
        detail = f"{type(exc).__name__}: {exc}"[:2_000]
        tools = []
    with connect() as db:
        ensure_schema(db, commit=False)
        db.execute(
            """UPDATE mcp_servers SET last_probe_at=?,last_probe_status=?,
                      last_probe_detail=?,updated_at=? WHERE id=?""",
            (_now(), status, detail, _now(), sid),
        )
        db.commit()
    return {"server_id": sid, "status": status, "detail": detail, "tool_count": len(tools)}
