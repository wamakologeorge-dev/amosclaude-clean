"""Signed terminal-v2 tickets for the Amosclaud workspace runtime.

The original terminal ticket remains available for backward compatibility.  This
module adds a versioned protocol that binds every ticket to a named terminal
session and an approved runtime profile.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from typing import Any
from urllib.parse import urlparse, urlunparse

_TERMINAL_ID_RE = re.compile(r"^term_[a-z0-9]{8,32}$")
_ALLOWED_PROFILES = frozenset({"bash", "sh", "python"})


def _runtime_url() -> str:
    return os.getenv("AMOSCLAUD_WORKSPACE_RUNTIME_URL", "").strip().rstrip("/")


def _runtime_token() -> str:
    return os.getenv("AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN", "").strip()


def _terminal_id(value: str) -> str:
    candidate = str(value or "").strip().lower()
    if not _TERMINAL_ID_RE.fullmatch(candidate):
        raise RuntimeError("Invalid terminal identifier")
    return candidate


def _profile(value: str) -> str:
    candidate = str(value or "bash").strip().lower()
    if candidate not in _ALLOWED_PROFILES:
        raise RuntimeError("Unsupported terminal profile")
    return candidate


def _ticket_payload(
    workspace_id: str,
    user_id: int,
    expires_at: int,
    nonce: str,
    terminal_id: str,
    profile: str,
) -> bytes:
    return (
        f"v2:{workspace_id}:{user_id}:{expires_at}:"
        f"{nonce}:{terminal_id}:{profile}"
    ).encode()


def _public_websocket_url(workspace_id: str, ticket: str) -> str:
    configured_public = os.getenv("AMOSCLAUD_WORKSPACE_PUBLIC_URL", "").strip()
    base = (configured_public or _runtime_url()).rstrip("/")
    if not base:
        raise RuntimeError("AMOSCLAUD_WORKSPACE_RUNTIME_URL is not configured")
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("Workspace runtime URL is invalid")
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = f"{parsed.path.rstrip('/')}/v2/terminal/{workspace_id}"
    return urlunparse((scheme, parsed.netloc, path, "", f"ticket={ticket}", ""))


def terminal_ticket(
    workspace: dict[str, Any],
    user_id: int,
    *,
    terminal_id: str,
    profile: str = "bash",
) -> dict[str, Any]:
    """Return a short-lived, single-use ticket for one terminal session."""

    token = _runtime_token()
    if not token:
        raise RuntimeError("Workspace runtime token is not configured")
    session_id = _terminal_id(terminal_id)
    selected_profile = _profile(profile)
    expires_at = int(time.time()) + 120
    nonce = secrets.token_urlsafe(18)
    workspace_id = str(workspace["id"])
    signature = hmac.new(
        token.encode(),
        _ticket_payload(
            workspace_id,
            int(user_id),
            expires_at,
            nonce,
            session_id,
            selected_profile,
        ),
        hashlib.sha256,
    ).hexdigest()
    envelope = {
        "version": 2,
        "workspace_id": workspace_id,
        "user_id": int(user_id),
        "expires_at": expires_at,
        "nonce": nonce,
        "terminal_id": session_id,
        "profile": selected_profile,
        "signature": signature,
    }
    encoded = (
        base64.urlsafe_b64encode(
            json.dumps(
                envelope,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        )
        .decode()
        .rstrip("=")
    )
    return {
        "protocol": "amosclaud-terminal-v2",
        "workspace_id": workspace_id,
        "terminal_id": session_id,
        "profile": selected_profile,
        "expires_at": expires_at,
        "websocket_url": _public_websocket_url(workspace_id, encoded),
    }
