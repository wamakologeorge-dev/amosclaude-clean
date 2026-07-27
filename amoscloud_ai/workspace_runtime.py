"""Control-plane client and persistent records for cloud workspaces."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from amoscloud_ai.api.routes.repositories import _db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _runtime_url() -> str:
    return os.getenv("AMOSCLAUD_WORKSPACE_RUNTIME_URL", "").strip().rstrip("/")


def _runtime_token() -> str:
    return os.getenv("AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN", "").strip()


def configured() -> bool:
    return bool(_runtime_url() and _runtime_token())


def ensure_workspace_table() -> None:
    """Create and repair the workspace record table without losing user data.

    Older deployments created this table before ``repository_id`` was unique.
    ``INSERT ... ON CONFLICT(repository_id)`` then raised an OperationalError and
    the Terminal page only showed the generic server-error message. The repair is
    intentionally idempotent so an existing Railway volume upgrades in place.
    """

    with _db() as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS cloud_workspaces (
                id TEXT PRIMARY KEY,
                repository_id INTEGER NOT NULL,
                owner_id INTEGER NOT NULL,
                runtime_status TEXT NOT NULL DEFAULT 'not_started',
                runtime_detail TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_started_at TEXT,
                last_stopped_at TEXT,
                FOREIGN KEY(repository_id) REFERENCES repositories(id) ON DELETE CASCADE,
                FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE
            )"""
        )
        columns = {
            str(row["name"])
            for row in db.execute("PRAGMA table_info(cloud_workspaces)").fetchall()
        }
        additions = {
            "runtime_status": "TEXT NOT NULL DEFAULT 'not_started'",
            "runtime_detail": "TEXT",
            "created_at": "TEXT",
            "updated_at": "TEXT",
            "last_started_at": "TEXT",
            "last_stopped_at": "TEXT",
        }
        for name, declaration in additions.items():
            if name not in columns:
                db.execute(
                    f"ALTER TABLE cloud_workspaces ADD COLUMN {name} {declaration}"
                )

        now = _now()
        db.execute(
            """UPDATE cloud_workspaces
               SET created_at=COALESCE(NULLIF(created_at,''), ?),
                   updated_at=COALESCE(NULLIF(updated_at,''), ?),
                   runtime_status=COALESCE(NULLIF(runtime_status,''), 'not_started')""",
            (now, now),
        )

        # Preserve the oldest workspace identifier for each repository and remove
        # duplicate records left by pre-unique deployments.
        duplicates = db.execute(
            """SELECT repository_id, MIN(rowid) AS keep_rowid
               FROM cloud_workspaces
               GROUP BY repository_id
               HAVING COUNT(*) > 1"""
        ).fetchall()
        for duplicate in duplicates:
            db.execute(
                "DELETE FROM cloud_workspaces WHERE repository_id=? AND rowid<>?",
                (duplicate["repository_id"], duplicate["keep_rowid"]),
            )
        db.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS
               idx_cloud_workspaces_repository_unique
               ON cloud_workspaces(repository_id)"""
        )
        db.commit()


def workspace_for_repository(repository_id: int, owner_id: int) -> dict[str, Any]:
    ensure_workspace_table()
    now = _now()
    workspace_id = f"ws_{secrets.token_hex(12)}"
    with _db() as db:
        db.execute(
            """INSERT OR IGNORE INTO cloud_workspaces
               (id, repository_id, owner_id, runtime_status, created_at, updated_at)
               VALUES (?, ?, ?, 'not_started', ?, ?)""",
            (workspace_id, repository_id, owner_id, now, now),
        )
        db.commit()
        row = db.execute(
            "SELECT * FROM cloud_workspaces WHERE repository_id=?",
            (repository_id,),
        ).fetchone()
    if not row or int(row["owner_id"]) != owner_id:
        raise RuntimeError("Repository workspace ownership is inconsistent")
    return dict(row)


def _record(
    workspace_id: str,
    status: str,
    detail: str | None = None,
    *,
    started: bool = False,
    stopped: bool = False,
) -> None:
    ensure_workspace_table()
    now = _now()
    assignments = ["runtime_status=?", "runtime_detail=?", "updated_at=?"]
    values: list[Any] = [status[:80], (detail or "")[:1000] or None, now]
    if started:
        assignments.append("last_started_at=?")
        values.append(now)
    if stopped:
        assignments.append("last_stopped_at=?")
        values.append(now)
    values.append(workspace_id)
    with _db() as db:
        db.execute(
            f"UPDATE cloud_workspaces SET {', '.join(assignments)} WHERE id=?",
            values,
        )
        db.commit()


def record_workspace_status(
    workspace_id: str,
    status: str,
    detail: str | None = None,
    *,
    started: bool = False,
    stopped: bool = False,
) -> None:
    """Public status recorder used by both external and managed runtimes."""

    _record(
        workspace_id,
        status,
        detail,
        started=started,
        stopped=stopped,
    )


def _headers() -> dict[str, str]:
    token = _runtime_token()
    if not token:
        raise RuntimeError("AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN is not configured")
    return {"Authorization": f"Bearer {token}"}


def _request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    base = _runtime_url()
    if not base:
        raise RuntimeError("AMOSCLAUD_WORKSPACE_RUNTIME_URL is not configured")
    with httpx.Client(timeout=30) as client:
        response = client.request(
            method,
            f"{base}{path}",
            headers={**_headers(), **kwargs.pop("headers", {})},
            **kwargs,
        )
    if response.status_code >= 400:
        try:
            message = response.json().get("detail")
        except (ValueError, AttributeError):
            message = response.text
        raise RuntimeError(
            str(message or f"Workspace runtime returned {response.status_code}")
        )
    if response.status_code == 204 or not response.content:
        return {}
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Workspace runtime returned an invalid response")
    return payload


def runtime_health() -> dict[str, Any]:
    if not configured():
        return {
            "configured": False,
            "ok": False,
            "detail": (
                "Set AMOSCLAUD_WORKSPACE_RUNTIME_URL and "
                "AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN."
            ),
        }
    try:
        payload = _request("GET", "/health")
        return {"configured": True, **payload}
    except RuntimeError:
        return {
            "configured": True,
            "ok": False,
            "detail": "Workspace runtime health check failed.",
        }


def start_workspace(
    workspace: dict[str, Any],
    *,
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        result = _request(
            "POST",
            "/v1/workspaces",
            json={
                "workspace_id": workspace["id"],
                "repository_id": int(workspace["repository_id"]),
                "owner_id": int(workspace["owner_id"]),
                "environment": environment or {},
            },
        )
    except RuntimeError as exc:
        _record(workspace["id"], "error", str(exc))
        raise
    _record(
        workspace["id"],
        str(result.get("status") or "running"),
        "provider=external",
        started=True,
    )
    return result


def stop_workspace(workspace: dict[str, Any]) -> dict[str, Any]:
    try:
        result = _request("POST", f"/v1/workspaces/{workspace['id']}/stop")
    except RuntimeError as exc:
        _record(workspace["id"], "error", str(exc))
        raise
    _record(
        workspace["id"],
        str(result.get("status") or "exited"),
        "provider=external",
        stopped=True,
    )
    return result


def delete_workspace(workspace: dict[str, Any]) -> None:
    _request("DELETE", f"/v1/workspaces/{workspace['id']}")


def remote_status(workspace: dict[str, Any]) -> dict[str, Any]:
    result = _request("GET", f"/v1/workspaces/{workspace['id']}")
    _record(
        workspace["id"],
        str(result.get("status") or "unknown"),
        "provider=external",
    )
    return result


def _ticket_payload(
    workspace_id: str,
    user_id: int,
    expires_at: int,
    nonce: str,
) -> bytes:
    return f"{workspace_id}:{user_id}:{expires_at}:{nonce}".encode()


def _public_websocket_url(workspace_id: str, ticket: str) -> str:
    configured_public = os.getenv("AMOSCLAUD_WORKSPACE_PUBLIC_URL", "").strip()
    base = (configured_public or _runtime_url()).rstrip("/")
    parsed = urlparse(base)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = f"{parsed.path.rstrip('/')}/v1/terminal/{workspace_id}"
    return urlunparse((scheme, parsed.netloc, path, "", f"ticket={ticket}", ""))


def terminal_ticket(workspace: dict[str, Any], user_id: int) -> dict[str, Any]:
    token = _runtime_token()
    if not token:
        raise RuntimeError("Workspace runtime token is not configured")
    expires_at = int(time.time()) + 120
    nonce = secrets.token_urlsafe(18)
    signature = hmac.new(
        token.encode(),
        _ticket_payload(workspace["id"], user_id, expires_at, nonce),
        hashlib.sha256,
    ).hexdigest()
    envelope = {
        "workspace_id": workspace["id"],
        "user_id": user_id,
        "expires_at": expires_at,
        "nonce": nonce,
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
        "workspace_id": workspace["id"],
        "expires_at": expires_at,
        "websocket_url": _public_websocket_url(workspace["id"], encoded),
        "provider": "external",
    }
