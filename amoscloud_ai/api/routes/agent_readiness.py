from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import _connect, get_user_from_session
from amoscloud_ai.autonomous_api_chain import AutonomousChainRequest, execute_autonomous_chain
from amoscloud_ai.model_services import readiness

router = APIRouter(prefix="/agent", tags=["autonomous-agent"])


class AutonomousKeyRequest(BaseModel):
    name: str = Field(default="Autonomous key", min_length=2, max_length=80)


class ConnectorRunRequest(BaseModel):
    objective: str = Field(..., min_length=1, max_length=12000)
    mode: str = "autonomous-check"
    branch: str = Field(default="main", pattern=r"^[A-Za-z0-9._/-]+$")
    conversation_id: str | None = Field(default=None, max_length=128)
    use_model: bool = False
    apply_changes: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


def _user(request: Request):
    user = get_user_from_session(request.cookies.get("amos_session"))
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to use Amosclaud Autonomous")
    return user


def _key_schema(db: sqlite3.Connection) -> None:
    db.executescript("""
    CREATE TABLE IF NOT EXISTS autonomous_api_keys (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      name TEXT NOT NULL,
      prefix TEXT NOT NULL,
      key_hash TEXT NOT NULL UNIQUE,
      created_at TEXT NOT NULL,
      last_used_at TEXT,
      revoked_at TEXT,
      FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_autonomous_keys_user ON autonomous_api_keys(user_id, revoked_at);
    """)
    db.commit()


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _connector_key(authorization: str | None, x_api_key: str | None) -> str:
    if x_api_key:
        return x_api_key.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def _connector_user(authorization: str | None, x_api_key: str | None) -> dict[str, Any]:
    raw = _connector_key(authorization, x_api_key)
    if not raw:
        raise HTTPException(status_code=401, detail="Provide an Amosclaud Autonomous API key")
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as db:
        _key_schema(db)
        row = db.execute(
            """SELECT users.id,users.name,users.email,users.is_admin,users.provider,autonomous_api_keys.id AS key_id
               FROM autonomous_api_keys
               JOIN users ON users.id=autonomous_api_keys.user_id
               WHERE autonomous_api_keys.key_hash=? AND autonomous_api_keys.revoked_at IS NULL""",
            (_hash_key(raw),),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid or revoked Amosclaud Autonomous API key")
        db.execute("UPDATE autonomous_api_keys SET last_used_at=? WHERE id=?", (now, row["key_id"]))
        db.commit()
    return dict(row)


@router.get("/readiness")
def agent_readiness(request: Request) -> dict:
    """Truthful backend view used by the Autonomous Cloud Agent frontend."""
    _user(request)
    result = readiness()
    result.update({
        "status": "ready" if result["ready"] else "needs_configuration",
        "agent": "Amosclaud Autonomous Cloud Agent",
        "api_chain": "amosclaud-autonomous-v1",
        "architecture": [
            "Authenticated user or connector key",
            "Conversation and task identity",
            "Autonomous Core Orchestrator",
            "Agent 1 — Receive and understand",
            "Agent 2 — Perceive repository evidence",
            "Agent 3 — Plan with the model when requested",
            "Agent 4 — Act when authorized",
            "Agent 5 — Verify and report",
            "Rollback recommendation for failed deployment",
            "Verified terminal output",
        ],
    })
    return result


@router.get("/keys")
def list_autonomous_keys(request: Request) -> dict:
    user = _user(request)
    with _connect() as db:
        _key_schema(db)
        rows = db.execute(
            "SELECT id,name,prefix,created_at,last_used_at,revoked_at FROM autonomous_api_keys WHERE user_id=? ORDER BY id DESC",
            (user["id"],),
        ).fetchall()
    return {"keys": [dict(row) for row in rows]}


@router.post("/keys", status_code=201)
def create_autonomous_key(body: AutonomousKeyRequest, request: Request) -> dict:
    user = _user(request)
    raw = "amos_aut_" + secrets.token_urlsafe(36)
    now = datetime.now(timezone.utc).isoformat()
    prefix = raw[:18]
    with _connect() as db:
        _key_schema(db)
        cursor = db.execute(
            "INSERT INTO autonomous_api_keys(user_id,name,prefix,key_hash,created_at) VALUES (?,?,?,?,?)",
            (user["id"], body.name.strip(), prefix, _hash_key(raw), now),
        )
        db.commit()
    return {"id": cursor.lastrowid, "name": body.name.strip(), "key": raw, "prefix": prefix, "created_at": now, "warning": "Copy this key now. Only its secure hash is stored."}


@router.post("/keys/{key_id}/rotate", status_code=201)
def rotate_autonomous_key(key_id: int, request: Request) -> dict:
    user = _user(request)
    raw = "amos_aut_" + secrets.token_urlsafe(36)
    now = datetime.now(timezone.utc).isoformat()
    prefix = raw[:18]
    with _connect() as db:
        _key_schema(db)
        old = db.execute("SELECT id,name FROM autonomous_api_keys WHERE id=? AND user_id=? AND revoked_at IS NULL", (key_id, user["id"])).fetchone()
        if not old:
            raise HTTPException(status_code=404, detail="Active Autonomous key not found")
        db.execute("UPDATE autonomous_api_keys SET revoked_at=? WHERE id=?", (now, key_id))
        cursor = db.execute("INSERT INTO autonomous_api_keys(user_id,name,prefix,key_hash,created_at) VALUES (?,?,?,?,?)", (user["id"], old["name"], prefix, _hash_key(raw), now))
        db.commit()
    return {"id": cursor.lastrowid, "name": old["name"], "key": raw, "prefix": prefix, "created_at": now, "warning": "The previous key is revoked. Copy this replacement now."}


@router.delete("/keys/{key_id}", status_code=204)
def revoke_autonomous_key(key_id: int, request: Request):
    user = _user(request)
    with _connect() as db:
        _key_schema(db)
        updated = db.execute("UPDATE autonomous_api_keys SET revoked_at=? WHERE id=? AND user_id=? AND revoked_at IS NULL", (datetime.now(timezone.utc).isoformat(), key_id, user["id"]))
        db.commit()
    if updated.rowcount != 1:
        raise HTTPException(status_code=404, detail="Active Autonomous key not found")
    return None


@router.post("/connector/run", summary="Run the complete Autonomous API chain from Codex or another trusted connector")
async def run_connector_task(
    body: ConnectorRunRequest,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    user = _connector_user(authorization, x_api_key)
    try:
        result = execute_autonomous_chain(
            AutonomousChainRequest(
                user_id=user["id"],
                user_name=user["name"],
                objective=body.objective,
                mode=body.mode,
                branch=body.branch,
                conversation_id=body.conversation_id,
                source="amosclaud-autonomous-codex-connector",
                use_model=body.use_model,
                apply_changes=body.apply_changes,
                metadata=body.metadata,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.payload
