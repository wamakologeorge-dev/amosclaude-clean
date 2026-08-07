"""Internal authenticated gateway used by the Amosclaud account MCP connector."""

from __future__ import annotations

from typing import Any

import httpx

from amoscloud_ai.api.routes import auth

ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
READ_METHODS = {"GET"}
WRITE_METHODS = ALLOWED_METHODS - READ_METHODS
PUBLIC_READ_PATHS = {"/health", "/ready", "/openapi.json", "/openapi.yaml"}
MAX_RESPONSE_BYTES = 2_000_000


class ConnectorGatewayError(RuntimeError):
    """Raised when a connector action cannot be safely routed."""


def normalize_platform_path(path: str, *, write: bool) -> str:
    cleaned = "/" + path.strip().lstrip("/")
    if "://" in cleaned or "\x00" in cleaned:
        raise ConnectorGatewayError("Use an Amosclaud API path, not a URL")
    if any(part == ".." for part in cleaned.split("/")):
        raise ConnectorGatewayError("Parent-path traversal is not allowed")
    if cleaned.startswith("/connectors/amosclaud/"):
        raise ConnectorGatewayError("The connector cannot recursively call its own OAuth or MCP paths")
    if write:
        if not cleaned.startswith("/api/v1/"):
            raise ConnectorGatewayError("Write actions must target an /api/v1/ Amosclaud endpoint")
    elif cleaned not in PUBLIC_READ_PATHS and not cleaned.startswith("/api/v1/"):
        raise ConnectorGatewayError("Read actions must target /api/v1/, /health, /ready, or OpenAPI")
    return cleaned


def required_scope(method: str, path: str) -> str:
    normalized_method = method.upper()
    normalized_path = normalize_platform_path(path, write=normalized_method in WRITE_METHODS)
    if normalized_method == "GET":
        if "/repositories" in normalized_path or normalized_path.startswith("/api/v1/github"):
            return "repositories:read"
        if any(segment in normalized_path for segment in ("/tasks", "/pipelines", "/agent")):
            return "tasks:read"
        return "platform:read"
    if normalized_method not in WRITE_METHODS:
        raise ConnectorGatewayError(f"Unsupported method: {normalized_method}")
    if normalized_path.startswith("/api/v1/admin"):
        return "admin:write"
    if "/deploy" in normalized_path:
        return "deployments:write"
    if "/repositories" in normalized_path or normalized_path.startswith("/api/v1/github"):
        return "repositories:write"
    if any(segment in normalized_path for segment in ("/tasks", "/pipelines", "/agent")):
        return "tasks:write"
    return "platform:write"


async def request_as_user(
    *,
    user_id: int,
    method: str,
    path: str,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | list[Any] | None = None,
) -> dict[str, Any]:
    """Execute one API request through the real platform using a temporary user session."""

    normalized_method = method.upper()
    if normalized_method not in ALLOWED_METHODS:
        raise ConnectorGatewayError(
            f"method must be one of: {', '.join(sorted(ALLOWED_METHODS))}"
        )
    normalized_path = normalize_platform_path(
        path,
        write=normalized_method in WRITE_METHODS,
    )

    with auth._connect() as db:
        user = db.execute(
            "SELECT id FROM users WHERE id=?",
            (int(user_id),),
        ).fetchone()
        if not user:
            raise ConnectorGatewayError("The connected Amosclaud account no longer exists")
        session_token = auth._create_session(db, int(user_id))

    try:
        # Import lazily to avoid a cycle while the combined platform app imports
        # this connector package during application startup.
        from amoscloud_ai.combined_app import app as platform_app

        transport = httpx.ASGITransport(app=platform_app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://amosclaud.internal",
            timeout=90,
            follow_redirects=False,
            cookies={auth.SESSION_COOKIE: session_token},
        ) as client:
            response = await client.request(
                normalized_method,
                normalized_path,
                params=query or None,
                json=body,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "amosclaud-account-connector/1.0",
                },
            )
    except httpx.HTTPError as exc:
        raise ConnectorGatewayError(
            f"Amosclaud internal API request failed: {type(exc).__name__}"
        ) from exc
    finally:
        with auth._connect() as db:
            db.execute(
                "DELETE FROM sessions WHERE token_hash=?",
                (auth._token_hash(session_token),),
            )
            db.commit()

    raw = response.content[:MAX_RESPONSE_BYTES]
    truncated = len(response.content) > MAX_RESPONSE_BYTES
    try:
        payload: Any = response.json()
    except ValueError:
        payload = raw.decode("utf-8", errors="replace")

    result = {
        "method": normalized_method,
        "path": normalized_path,
        "status_code": response.status_code,
        "ok": response.is_success,
        "body": payload,
        "truncated": truncated,
    }
    if response.is_error:
        result["error"] = "amosclaud_api_error"
    return result
