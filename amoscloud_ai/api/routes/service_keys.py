"""Administrator-managed, scoped service credentials for Amosclaud servers."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes import auth

admin_router = APIRouter(prefix="/admin/service-keys", tags=["service-key-control"])
verify_router = APIRouter(prefix="/service-keys", tags=["service-key-authentication"])

ALLOWED_SCOPES = {
    "status:read",
    "bundles:read",
    "bundles:write",
    "buddies:heartbeat",
    "tasks:read",
    "tasks:write",
    "model:invoke",
}


class ServiceKeyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    service: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    scopes: list[str] = Field(min_length=1, max_length=20)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _db() -> sqlite3.Connection:
    db = auth._connect()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS service_api_keys (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      service TEXT NOT NULL,
      prefix TEXT NOT NULL,
      key_hash TEXT NOT NULL UNIQUE,
      scopes_json TEXT NOT NULL,
      created_by_user_id INTEGER NOT NULL,
      created_at TEXT NOT NULL,
      last_used_at TEXT,
      revoked_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_service_keys_active
      ON service_api_keys(revoked_at,service);
    CREATE TABLE IF NOT EXISTS service_key_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      key_id INTEGER,
      admin_user_id INTEGER,
      action TEXT NOT NULL,
      detail TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL
    );
    """)
    db.commit()
    return db


def _admin_user(amos_session: str | None = Cookie(default=None)) -> sqlite3.Row:
    user = auth.get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not bool(user["is_admin"]):
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


def _scopes(values: list[str]) -> list[str]:
    scopes = sorted({value.strip().lower() for value in values if value.strip()})
    invalid = sorted(set(scopes) - ALLOWED_SCOPES)
    if invalid:
        raise HTTPException(status_code=422, detail=f"Unsupported service-key scopes: {invalid}")
    if not scopes:
        raise HTTPException(status_code=422, detail="At least one service-key scope is required")
    return scopes


def _public(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "service": row["service"],
        "prefix": row["prefix"],
        "scopes": json.loads(row["scopes_json"]),
        "created_by_user_id": row["created_by_user_id"],
        "created_at": row["created_at"],
        "last_used_at": row["last_used_at"],
        "revoked_at": row["revoked_at"],
        "status": "revoked" if row["revoked_at"] else "active",
    }


def _issue(db: sqlite3.Connection, body: ServiceKeyCreate, admin_id: int) -> dict[str, Any]:
    raw = "amos_svc_" + secrets.token_urlsafe(40)
    scopes = _scopes(body.scopes)
    created_at = _now()
    cursor = db.execute(
        """INSERT INTO service_api_keys(
             name,service,prefix,key_hash,scopes_json,created_by_user_id,created_at
           ) VALUES (?,?,?,?,?,?,?)""",
        (
            body.name.strip(),
            body.service.strip().lower(),
            raw[:20],
            _hash(raw),
            json.dumps(scopes),
            admin_id,
            created_at,
        ),
    )
    key_id = int(cursor.lastrowid)
    db.execute(
        "INSERT INTO service_key_events(key_id,admin_user_id,action,created_at) VALUES (?,?,?,?)",
        (key_id, admin_id, "created", created_at),
    )
    row = db.execute("SELECT * FROM service_api_keys WHERE id=?", (key_id,)).fetchone()
    return {
        **_public(row),
        "key": raw,
        "warning": "Copy this service key now. Amosclaud stores only its SHA-256 hash.",
    }


@admin_router.get("/status")
def control_status(admin: sqlite3.Row = Depends(_admin_user)) -> dict[str, Any]:
    del admin
    with _db() as db:
        active = int(
            db.execute(
                "SELECT COUNT(*) FROM service_api_keys WHERE revoked_at IS NULL"
            ).fetchone()[0]
        )
        revoked = int(
            db.execute(
                "SELECT COUNT(*) FROM service_api_keys WHERE revoked_at IS NOT NULL"
            ).fetchone()[0]
        )
        used = int(
            db.execute(
                "SELECT COUNT(*) FROM service_api_keys WHERE last_used_at IS NOT NULL"
            ).fetchone()[0]
        )
    return {
        "status": "operational",
        "service": "amosclaud-service-key-authority",
        "storage": "hashed-only",
        "active_keys": active,
        "revoked_keys": revoked,
        "used_keys": used,
        "allowed_scopes": sorted(ALLOWED_SCOPES),
        "generated_at": _now(),
    }


@admin_router.get("")
def list_keys(admin: sqlite3.Row = Depends(_admin_user)) -> dict[str, Any]:
    del admin
    with _db() as db:
        rows = db.execute("SELECT * FROM service_api_keys ORDER BY id DESC LIMIT 500").fetchall()
    return {"object": "list", "data": [_public(row) for row in rows]}


@admin_router.post("", status_code=201)
def create_key(
    body: ServiceKeyCreate,
    admin: sqlite3.Row = Depends(_admin_user),
) -> dict[str, Any]:
    with _db() as db:
        result = _issue(db, body, int(admin["id"]))
        db.commit()
    return result


@admin_router.post("/{key_id}/rotate", status_code=201)
def rotate_key(key_id: int, admin: sqlite3.Row = Depends(_admin_user)) -> dict[str, Any]:
    with _db() as db:
        old = db.execute(
            "SELECT * FROM service_api_keys WHERE id=? AND revoked_at IS NULL", (key_id,)
        ).fetchone()
        if not old:
            raise HTTPException(status_code=404, detail="Active service key not found")
        revoked_at = _now()
        db.execute("UPDATE service_api_keys SET revoked_at=? WHERE id=?", (revoked_at, key_id))
        db.execute(
            """INSERT INTO service_key_events(key_id,admin_user_id,action,created_at)
               VALUES (?,?,?,?)""",
            (key_id, int(admin["id"]), "rotated", revoked_at),
        )
        result = _issue(
            db,
            ServiceKeyCreate(
                name=old["name"],
                service=old["service"],
                scopes=json.loads(old["scopes_json"]),
            ),
            int(admin["id"]),
        )
        db.commit()
    result["rotated_from_key_id"] = key_id
    return result


@admin_router.delete("/{key_id}", status_code=204)
def revoke_key(key_id: int, admin: sqlite3.Row = Depends(_admin_user)) -> Response:
    with _db() as db:
        revoked_at = _now()
        updated = db.execute(
            "UPDATE service_api_keys SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
            (revoked_at, key_id),
        )
        if updated.rowcount != 1:
            raise HTTPException(status_code=404, detail="Active service key not found")
        db.execute(
            """INSERT INTO service_key_events(key_id,admin_user_id,action,created_at)
               VALUES (?,?,?,?)""",
            (key_id, int(admin["id"]), "revoked", revoked_at),
        )
        db.commit()
    return Response(status_code=204)


def authenticate_service_key(raw: str, required_scope: str | None = None) -> dict[str, Any]:
    if not raw:
        raise HTTPException(status_code=401, detail="Provide an Amosclaud service key")
    with _db() as db:
        row = db.execute(
            "SELECT * FROM service_api_keys WHERE key_hash=? AND revoked_at IS NULL",
            (_hash(raw),),
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=401,
                detail="Invalid or revoked Amosclaud service key",
            )
        scopes = json.loads(row["scopes_json"])
        if required_scope and required_scope not in scopes:
            raise HTTPException(
                status_code=403,
                detail=f"Service key requires scope: {required_scope}",
            )
        used_at = _now()
        db.execute("UPDATE service_api_keys SET last_used_at=? WHERE id=?", (used_at, row["id"]))
        db.execute(
            "INSERT INTO service_key_events(key_id,action,detail,created_at) VALUES (?,?,?,?)",
            (row["id"], "verified", required_scope or "", used_at),
        )
        db.commit()
    return {**_public(row), "last_used_at": used_at, "authenticated": True}


@verify_router.get("/verify")
def verify_key(
    scope: str | None = None,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    bearer = ""
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()
    raw = (x_api_key or "").strip() or bearer
    return authenticate_service_key(raw, scope)
