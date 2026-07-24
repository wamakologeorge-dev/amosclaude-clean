"""Signed outbound webhooks for Amosclaud developer integrations."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import _connect, get_user_from_session

router = APIRouter(prefix="/webhooks", tags=["developer-webhooks"])
SUPPORTED_EVENTS = {"task.completed", "task.failed", "task.cancelled"}


class WebhookCreate(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    events: list[str] = Field(default_factory=lambda: sorted(SUPPORTED_EVENTS), min_length=1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fernet() -> Fernet:
    key = os.getenv("AMOSCLAUD_MASTER_KEY", "")
    if not key:
        if os.getenv("AMOSCLAUD_ENV", "development").lower() in {"production", "prod"}:
            raise RuntimeError("AMOSCLAUD_MASTER_KEY is required for production webhooks")
        key = "amosclaud-local-development-webhook-key"
    derived = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
    return Fernet(derived)


def _encrypt(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError(
            "Webhook secret cannot be decrypted with the configured master key"
        ) from exc


def _validate_url(value: str) -> str:
    parsed = urlparse(value.strip())
    production = os.getenv("AMOSCLAUD_ENV", "development").lower() in {"production", "prod"}
    if parsed.username or parsed.password or not parsed.hostname:
        raise HTTPException(status_code=422, detail="Webhook URL is invalid")
    if parsed.scheme != "https" and not (
        not production
        and parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise HTTPException(status_code=422, detail="Webhook URL must use HTTPS")
    return value.strip()


def _user(token: str | None):
    user = get_user_from_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to manage webhooks")
    return user


def _public(row) -> dict:
    return {
        "id": row["id"],
        "url": row["url"],
        "events": json.loads(row["events_json"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "last_success_at": row["last_success_at"],
        "last_failure_at": row["last_failure_at"],
        "failure_count": row["failure_count"],
    }


@router.post("", status_code=201)
def create_webhook(body: WebhookCreate, amos_session: str | None = Cookie(default=None)) -> dict:
    user = _user(amos_session)
    events = sorted(set(body.events))
    unknown = set(events) - SUPPORTED_EVENTS
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"Unsupported events: {', '.join(sorted(unknown))}"
        )
    webhook_id = f"wh_{uuid.uuid4().hex}"
    secret = f"whsec_{secrets.token_urlsafe(32)}"
    with _connect() as db:
        db.execute(
            """INSERT INTO developer_webhooks
               (id,user_id,url,events_json,secret_ciphertext,status,created_at)
               VALUES (?,?,?,?,?,'active',?)""",
            (
                webhook_id,
                user["id"],
                _validate_url(body.url),
                json.dumps(events),
                _encrypt(secret),
                _now(),
            ),
        )
        db.commit()
        row = db.execute("SELECT * FROM developer_webhooks WHERE id=?", (webhook_id,)).fetchone()
    return {
        **_public(row),
        "secret": secret,
        "secret_notice": "Store this secret now; it will not be shown again.",
    }


@router.get("")
def list_webhooks(amos_session: str | None = Cookie(default=None)) -> list[dict]:
    user = _user(amos_session)
    with _connect() as db:
        rows = db.execute(
            "SELECT * FROM developer_webhooks WHERE user_id=? ORDER BY created_at DESC",
            (user["id"],),
        ).fetchall()
    return [_public(row) for row in rows]


@router.delete("/{webhook_id}", status_code=204)
def delete_webhook(webhook_id: str, amos_session: str | None = Cookie(default=None)) -> None:
    user = _user(amos_session)
    with _connect() as db:
        cursor = db.execute(
            "DELETE FROM developer_webhooks WHERE id=? AND user_id=?", (webhook_id, user["id"])
        )
        db.commit()
    if cursor.rowcount != 1:
        raise HTTPException(status_code=404, detail="Webhook not found")


def signature(secret: str, timestamp: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"v1={digest}"


def dispatch_webhook_event(user_id: int, event_type: str, payload: dict) -> None:
    """Deliver a terminal task event. Failures are recorded and never fail the task."""
    if event_type not in SUPPORTED_EVENTS:
        return
    event_id = f"evt_{uuid.uuid4().hex}"
    envelope = {"id": event_id, "type": event_type, "created_at": _now(), "data": payload}
    body = json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode()
    with _connect() as db:
        try:
            hooks = db.execute(
                "SELECT * FROM developer_webhooks WHERE user_id=? AND status='active'", (user_id,)
            ).fetchall()
        except sqlite3.OperationalError:
            # Legacy/test databases may not have run application startup yet.
            return
        for hook in hooks:
            if event_type not in json.loads(hook["events_json"]):
                continue
            delivery_id = f"del_{uuid.uuid4().hex}"
            timestamp = str(int(datetime.now(timezone.utc).timestamp()))
            code = None
            error = None
            status = "failed"
            try:
                response = httpx.post(
                    hook["url"],
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "Amosclaud-Webhooks/1.0",
                        "X-Amosclaud-Event": event_type,
                        "X-Amosclaud-Event-Id": event_id,
                        "X-Amosclaud-Timestamp": timestamp,
                        "X-Amosclaud-Signature": signature(
                            _decrypt(hook["secret_ciphertext"]), timestamp, body
                        ),
                    },
                    timeout=10,
                    follow_redirects=False,
                )
                code = response.status_code
                response.raise_for_status()
                status = "delivered"
            except Exception as exc:
                error = str(exc)[:1000]
            db.execute(
                """INSERT INTO webhook_deliveries
                   (id,webhook_id,event_id,event_type,status,attempts,response_code,error,created_at,delivered_at)
                   VALUES (?,?,?,?,?,1,?,?,?,?)""",
                (
                    delivery_id,
                    hook["id"],
                    event_id,
                    event_type,
                    status,
                    code,
                    error,
                    _now(),
                    _now() if status == "delivered" else None,
                ),
            )
            if status == "delivered":
                db.execute(
                    "UPDATE developer_webhooks SET last_success_at=?,failure_count=0 WHERE id=?",
                    (_now(), hook["id"]),
                )
            else:
                db.execute(
                    "UPDATE developer_webhooks SET last_failure_at=?,failure_count=failure_count+1 WHERE id=?",
                    (_now(), hook["id"]),
                )
        db.commit()
