"""Per-user Amosclaud Autonomous API key management."""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from amoscloud_ai.api.routes.auth import _connect, get_user_from_session

router = APIRouter(prefix="/autonomous/keys", tags=["autonomous-keys"])

AVAILABLE_SKILLS = frozenset(
    {
        "answer",
        "inspect",
        "plan",
        "build",
        "fix",
        "test",
        "deploy",
        "monitor",
    }
)
DEFAULT_SKILLS = (
    "answer",
    "inspect",
    "plan",
    "build",
    "fix",
    "test",
    "monitor",
)


class KeyCreateRequest(BaseModel):
    name: str = Field(default="Autonomous key", min_length=2, max_length=80)
    skills: list[str] = Field(default_factory=lambda: list(DEFAULT_SKILLS))

    @field_validator("skills")
    @classmethod
    def validate_skills(cls, value: list[str]) -> list[str]:
        normalized = sorted({item.strip().lower() for item in value if item.strip()})
        unknown = sorted(set(normalized) - AVAILABLE_SKILLS)
        if unknown:
            raise ValueError(f"Unknown Autonomous skills: {', '.join(unknown)}")
        if not normalized:
            raise ValueError("At least one Autonomous skill is required")
        return normalized


def _schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS autonomous_api_keys (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL,
          name TEXT NOT NULL,
          prefix TEXT NOT NULL,
          key_hash TEXT NOT NULL UNIQUE,
          skills TEXT NOT NULL DEFAULT '["answer","inspect","plan"]',
          created_at TEXT NOT NULL,
          last_used_at TEXT,
          revoked_at TEXT,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_autonomous_keys_user
        ON autonomous_api_keys(user_id, revoked_at);
        """
    )
    columns = {
        str(row["name"])
        for row in db.execute("PRAGMA table_info(autonomous_api_keys)").fetchall()
    }
    if "skills" not in columns:
        db.execute(
            "ALTER TABLE autonomous_api_keys "
            "ADD COLUMN skills TEXT NOT NULL "
            "DEFAULT '[\"answer\",\"inspect\",\"plan\"]'"
        )
    db.commit()


def _user(request: Request):
    user = get_user_from_session(request.cookies.get("amos_session"))
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to manage Autonomous keys")
    return user


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _decode_skills(raw: str | None) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        value = []
    return sorted(
        item for item in value if isinstance(item, str) and item in AVAILABLE_SKILLS
    )


@router.get("")
def list_keys(request: Request) -> dict:
    user = _user(request)
    with _connect() as db:
        _schema(db)
        rows = db.execute(
            "SELECT id,name,prefix,skills,created_at,last_used_at,revoked_at "
            "FROM autonomous_api_keys WHERE user_id=? ORDER BY id DESC",
            (user["id"],),
        ).fetchall()
    keys = []
    for row in rows:
        item = dict(row)
        item["skills"] = _decode_skills(item.get("skills"))
        keys.append(item)
    return {"available_skills": sorted(AVAILABLE_SKILLS), "keys": keys}


@router.post("", status_code=201)
def create_key(body: KeyCreateRequest, request: Request) -> dict:
    user = _user(request)
    raw = "amos_aut_" + secrets.token_urlsafe(36)
    now = datetime.now(timezone.utc).isoformat()
    prefix = raw[:18]
    skills = json.dumps(body.skills, separators=(",", ":"))
    with _connect() as db:
        _schema(db)
        cursor = db.execute(
            "INSERT INTO autonomous_api_keys"
            "(user_id,name,prefix,key_hash,skills,created_at) VALUES (?,?,?,?,?,?)",
            (user["id"], body.name.strip(), prefix, _hash(raw), skills, now),
        )
        db.commit()
    return {
        "id": cursor.lastrowid,
        "name": body.name.strip(),
        "key": raw,
        "prefix": prefix,
        "skills": body.skills,
        "created_at": now,
        "warning": (
            "Copy this key now. Amosclaud stores only its hash and cannot "
            "display it again."
        ),
    }


@router.post("/{key_id}/rotate", status_code=201)
def rotate_key(key_id: int, request: Request) -> dict:
    user = _user(request)
    raw = "amos_aut_" + secrets.token_urlsafe(36)
    now = datetime.now(timezone.utc).isoformat()
    prefix = raw[:18]
    with _connect() as db:
        _schema(db)
        row = db.execute(
            "SELECT id,name,skills FROM autonomous_api_keys "
            "WHERE id=? AND user_id=? AND revoked_at IS NULL",
            (key_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Active Autonomous key not found")
        db.execute(
            "UPDATE autonomous_api_keys SET revoked_at=? WHERE id=?",
            (now, key_id),
        )
        cursor = db.execute(
            "INSERT INTO autonomous_api_keys"
            "(user_id,name,prefix,key_hash,skills,created_at) VALUES (?,?,?,?,?,?)",
            (user["id"], row["name"], prefix, _hash(raw), row["skills"], now),
        )
        db.commit()
    return {
        "id": cursor.lastrowid,
        "name": row["name"],
        "key": raw,
        "prefix": prefix,
        "skills": _decode_skills(row["skills"]),
        "created_at": now,
        "warning": "The previous key was revoked. Copy this replacement now.",
    }


@router.delete("/{key_id}", status_code=204)
def revoke_key(key_id: int, request: Request):
    user = _user(request)
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as db:
        _schema(db)
        updated = db.execute(
            "UPDATE autonomous_api_keys SET revoked_at=? "
            "WHERE id=? AND user_id=? AND revoked_at IS NULL",
            (now, key_id, user["id"]),
        )
        db.commit()
    if updated.rowcount != 1:
        raise HTTPException(status_code=404, detail="Active Autonomous key not found")
    return None


def authenticate_autonomous_key(raw: str | None):
    if not raw:
        return None
    with _connect() as db:
        _schema(db)
        row = db.execute(
            """
            SELECT users.id,users.name,users.email,users.is_admin,users.provider,
                   autonomous_api_keys.id AS key_id,
                   autonomous_api_keys.skills AS autonomous_skills
            FROM autonomous_api_keys
            JOIN users ON users.id=autonomous_api_keys.user_id
            WHERE autonomous_api_keys.key_hash=?
              AND autonomous_api_keys.revoked_at IS NULL
            """,
            (_hash(raw),),
        ).fetchone()
        if row:
            db.execute(
                "UPDATE autonomous_api_keys SET last_used_at=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), row["key_id"]),
            )
            db.commit()
        return row


def autonomous_key_skills(user) -> frozenset[str]:
    if not user or "autonomous_skills" not in user.keys():
        return frozenset()
    return frozenset(_decode_skills(user["autonomous_skills"]))
