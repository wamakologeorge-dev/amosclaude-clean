"""Configuration and validation for the Amosclaud account OAuth server."""

from __future__ import annotations

import hashlib
import os
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import HTTPException

from amoscloud_ai.public_url_policy import normalize_public_amosclaud_url

CONNECTOR_BASE_PATH = "/connectors/amosclaud/v1"
OAUTH_PATH = f"{CONNECTOR_BASE_PATH}/oauth"
MCP_PATH = f"{CONNECTOR_BASE_PATH}/mcp"

ACCESS_TOKEN_SECONDS = max(
    300,
    min(
        int(os.getenv("AMOSCLAUD_CONNECTOR_ACCESS_TOKEN_SECONDS", "3600")),
        24 * 60 * 60,
    ),
)
REFRESH_TOKEN_SECONDS = max(
    24 * 60 * 60,
    min(
        int(
            os.getenv(
                "AMOSCLAUD_CONNECTOR_REFRESH_TOKEN_SECONDS",
                str(30 * 24 * 60 * 60),
            )
        ),
        180 * 24 * 60 * 60,
    ),
)
AUTHORIZATION_CODE_SECONDS = 10 * 60
CONSENT_SECONDS = 10 * 60

BASE_SCOPES = {
    "account:read",
    "platform:read",
    "platform:write",
    "repositories:read",
    "repositories:write",
    "tasks:read",
    "tasks:write",
    "deployments:write",
}
ADMIN_SCOPE = "admin:write"
ALL_SCOPES = BASE_SCOPES | {ADMIN_SCOPE}
PKCE_VALUE_RE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")


def now() -> int:
    return int(time.time())


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def public_base_url() -> str:
    configured = os.getenv("AMOSCLAUD_PUBLIC_URL") or os.getenv("AMOSCLAUD_API_URL")
    return normalize_public_amosclaud_url(configured or "https://www.amosclaud.com")


def oauth_issuer_url() -> str:
    return f"{public_base_url()}{OAUTH_PATH}"


def connector_resource_url() -> str:
    return f"{public_base_url()}{MCP_PATH}"


def authorization_server_metadata_path() -> str:
    return f"/.well-known/oauth-authorization-server{OAUTH_PATH}"


def protected_resource_metadata_path() -> str:
    return f"/.well-known/oauth-protected-resource{MCP_PATH}"


def valid_redirect_uri(value: str) -> str:
    cleaned = value.strip()
    parsed = urlsplit(cleaned)
    if parsed.fragment:
        raise HTTPException(
            status_code=400, detail="OAuth redirect URI must not contain a fragment"
        )
    host = (parsed.hostname or "").lower()
    if not host or parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="OAuth redirect URI has an invalid authority")
    scheme = parsed.scheme.lower()
    secure = scheme == "https"
    local = scheme == "http" and host in {"localhost", "127.0.0.1", "::1"}
    if not (secure or local):
        raise HTTPException(
            status_code=400,
            detail="OAuth redirect URI must use HTTPS or an HTTP localhost callback",
        )
    return cleaned


def valid_pkce_value(value: str, *, name: str) -> str:
    cleaned = value.strip()
    if not PKCE_VALUE_RE.fullmatch(cleaned):
        raise HTTPException(
            status_code=400,
            detail=f"OAuth {name} must be 43-128 unreserved ASCII characters",
        )
    return cleaned


def redirect_with_params(uri: str, **params: str | None) -> str:
    parts = urlsplit(uri)
    query = list(parse_qsl(parts.query, keep_blank_values=True))
    query.extend((key, value) for key, value in params.items() if value is not None)
    return urlunsplit(parts._replace(query=urlencode(query)))


def requested_scopes(raw: str | None, *, is_admin: bool) -> list[str]:
    requested = {item.strip() for item in (raw or "").split() if item.strip()}
    if not requested:
        requested = set(ALL_SCOPES if is_admin else BASE_SCOPES)
    unknown = requested - ALL_SCOPES
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported OAuth scopes: {', '.join(sorted(unknown))}",
        )
    if ADMIN_SCOPE in requested and not is_admin:
        raise HTTPException(status_code=403, detail="Administrator scope requires an administrator")
    requested.add("account:read")
    return sorted(requested)
