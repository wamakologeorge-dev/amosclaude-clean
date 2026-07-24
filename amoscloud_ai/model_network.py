"""Outbound-only discovery and leasing for Amosclaud model stations."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import _connect
from amoscloud_ai.api.routes.task_router import _ensure_schema, _loads, _runner_auth

router = APIRouter(prefix="/model-network", tags=["model-network"])
ONLINE_WINDOW = timedelta(seconds=90)


class ModelCompletion(BaseModel):
    status: str = Field(pattern="^(completed|failed)$")
    reply: str | None = Field(default=None, max_length=100_000)
    runtime: str = Field(default="station", max_length=100)
    error: str | None = Field(default=None, max_length=500)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cipher() -> Fernet:
    secret = os.getenv("AMOSCLAUD_MASTER_KEY", "").strip()
    if not secret:
        raise RuntimeError("AMOSCLAUD_MASTER_KEY is required for model-network routing")
    key = base64.urlsafe_b64encode(
        hashlib.sha256(f"amosclaud:model-network:v1:{secret}".encode()).digest()
    )
    return Fernet(key)


def _encrypt(value: dict[str, Any]) -> str:
    return _cipher().encrypt(json.dumps(value, separators=(",", ":")).encode()).decode()


def _decrypt(value: str) -> dict[str, Any]:
    try:
        return json.loads(_cipher().decrypt(value.encode()).decode())
    except (InvalidToken, json.JSONDecodeError) as error:
        raise RuntimeError("Model-network payload cannot be decrypted") from error


def _ensure_network_schema(db) -> None:
    _ensure_schema(db)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS model_network_requests (
            id TEXT PRIMARY KEY,
            owner_user_id INTEGER NOT NULL,
            station_id TEXT,
            status TEXT NOT NULL,
            payload_ciphertext TEXT,
            response_ciphertext TEXT,
            payload_hash TEXT NOT NULL,
            model TEXT NOT NULL,
            runtime TEXT,
            error_type TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            claimed_at TEXT,
            completed_at TEXT,
            delivered_at TEXT,
            FOREIGN KEY(station_id) REFERENCES task_runners(id)
        );
        CREATE INDEX IF NOT EXISTS idx_model_network_queue
          ON model_network_requests(owner_user_id,status,created_at);
        """)
    db.commit()


def _expire_requests(db) -> None:
    """Remove sensitive payloads when a lease can no longer be delivered."""
    db.execute(
        """UPDATE model_network_requests
           SET status='failed',payload_ciphertext=NULL,response_ciphertext=NULL,
               error_type='Expired',completed_at=?
           WHERE status IN ('queued','claimed') AND expires_at<=?""",
        (_now(), _now()),
    )
    db.commit()


def _owner_id() -> int | None:
    raw = os.getenv("AMOSCLAUD_NETWORK_OWNER_USER_ID", "").strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def _eligible_station(row) -> bool:
    capabilities = _loads(row["capabilities_json"], [])
    system = _loads(row["system_json"], {})
    model = system.get("model", {}) if isinstance(system, dict) else {}
    try:
        seen = datetime.fromisoformat(row["last_seen_at"] or "")
    except ValueError:
        return False
    return (
        "model.inference" in capabilities
        and bool(model.get("ready"))
        and datetime.now(timezone.utc) - seen <= ONLINE_WINDOW
        and not row["revoked_at"]
    )


def network_status() -> dict[str, Any]:
    owner_id = _owner_id()
    if owner_id is None:
        return {
            "configured": False,
            "ready_stations": 0,
            "detail": "network owner is not configured",
        }
    with _connect() as db:
        _ensure_network_schema(db)
        _expire_requests(db)
        rows = db.execute("SELECT * FROM task_runners WHERE user_id=?", (owner_id,)).fetchall()
    eligible = [row for row in rows if _eligible_station(row)]
    return {"configured": True, "ready_stations": len(eligible), "ready": bool(eligible)}


def request_inference(
    history: list[dict[str, str]], system_prompt: str, *, timeout: float | None = None
) -> dict[str, str] | None:
    """Queue encrypted inference and wait briefly for an outbound station claim."""
    owner_id = _owner_id()
    if owner_id is None:
        return None
    timeout = max(1.0, min(timeout or float(os.getenv("AMOSCLAUD_NETWORK_TIMEOUT", "35")), 120.0))
    payload = {
        "messages": [{"role": "system", "content": system_prompt}, *history],
        "model": os.getenv("AMOSCLAUD_MODEL", "amosclaud-folder-v1"),
        "max_tokens": 1200,
        "temperature": 0.2,
    }
    encoded = json.dumps(payload, sort_keys=True).encode()
    request_id = "modelreq_" + uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    with _connect() as db:
        _ensure_network_schema(db)
        _expire_requests(db)
        rows = db.execute("SELECT * FROM task_runners WHERE user_id=?", (owner_id,)).fetchall()
        if not any(_eligible_station(row) for row in rows):
            return None
        db.execute(
            """INSERT INTO model_network_requests
               (id,owner_user_id,status,payload_ciphertext,payload_hash,model,created_at,expires_at)
               VALUES (?,?,'queued',?,?,?,?,?)""",
            (
                request_id,
                owner_id,
                _encrypt(payload),
                hashlib.sha256(encoded).hexdigest(),
                payload["model"],
                now.isoformat(),
                (now + timedelta(seconds=timeout + 15)).isoformat(),
            ),
        )
        db.commit()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _connect() as db:
            _ensure_network_schema(db)
            row = db.execute(
                "SELECT * FROM model_network_requests WHERE id=?", (request_id,)
            ).fetchone()
            if row and row["status"] == "completed" and row["response_ciphertext"]:
                result = _decrypt(row["response_ciphertext"])
                db.execute(
                    """UPDATE model_network_requests
                       SET payload_ciphertext=NULL,response_ciphertext=NULL,status='delivered',delivered_at=?
                       WHERE id=?""",
                    (_now(), request_id),
                )
                db.commit()
                return result
            if row and row["status"] == "failed":
                return None
        time.sleep(0.1)
    with _connect() as db:
        _ensure_network_schema(db)
        db.execute(
            """UPDATE model_network_requests SET status='failed',payload_ciphertext=NULL,
               error_type='NetworkTimeout',completed_at=? WHERE id=? AND status IN ('queued','claimed')""",
            (_now(), request_id),
        )
        db.commit()
    return None


@router.post("/stations/{station_id}/claim")
def claim_model_request(
    station_id: str, authorization: str | None = Header(default=None)
) -> dict[str, Any] | None:
    with _connect() as db:
        _ensure_network_schema(db)
        station = _runner_auth(db, station_id, authorization)
        if not _eligible_station(station):
            return None
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            """SELECT * FROM model_network_requests
               WHERE owner_user_id=? AND status='queued' AND expires_at>?
               ORDER BY created_at LIMIT 1""",
            (station["user_id"], _now()),
        ).fetchone()
        if not row:
            db.commit()
            return None
        updated = db.execute(
            """UPDATE model_network_requests SET status='claimed',station_id=?,claimed_at=?
               WHERE id=? AND status='queued'""",
            (station_id, _now(), row["id"]),
        )
        if updated.rowcount != 1:
            db.rollback()
            return None
        db.commit()
        return {"id": row["id"], **_decrypt(row["payload_ciphertext"])}


@router.post("/stations/{station_id}/requests/{request_id}/complete")
def complete_model_request(
    station_id: str,
    request_id: str,
    body: ModelCompletion,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    with _connect() as db:
        _ensure_network_schema(db)
        station = _runner_auth(db, station_id, authorization)
        row = db.execute(
            """SELECT * FROM model_network_requests
               WHERE id=? AND station_id=? AND owner_user_id=? AND status='claimed'""",
            (request_id, station_id, station["user_id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Claimed model request not found")
        if body.status == "completed" and not (body.reply or "").strip():
            raise HTTPException(status_code=422, detail="Completed inference requires a reply")
        response = (
            _encrypt({"reply": body.reply.strip(), "runtime": body.runtime}) if body.reply else None
        )
        db.execute(
            """UPDATE model_network_requests SET status=?,response_ciphertext=?,payload_ciphertext=NULL,
               runtime=?,error_type=?,completed_at=? WHERE id=?""",
            (
                body.status,
                response,
                body.runtime,
                (body.error or "")[:100] or None,
                _now(),
                request_id,
            ),
        )
        db.commit()
    return {"ok": True, "request_id": request_id, "status": body.status}
