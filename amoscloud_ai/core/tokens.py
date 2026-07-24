from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


class TokenError(RuntimeError):
    pass


class AmosclaudTokenService:
    """Issue and verify Amosclaud-owned bearer tokens.

    Raw tokens are shown once. Only SHA-256 hashes are stored.
    """

    PREFIX = "amo_token_"

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS amo_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_hash TEXT NOT NULL UNIQUE,
                    token_hint TEXT NOT NULL,
                    name TEXT NOT NULL,
                    owner_id INTEGER NOT NULL,
                    scopes TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    last_used_at TEXT,
                    revoked_at TEXT
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def issue(
        self,
        *,
        name: str,
        owner_id: int,
        scopes: list[str],
        expires_in_days: int | None = 90,
    ) -> dict:
        clean_name = name.strip()
        if not clean_name or len(clean_name) > 120:
            raise TokenError("Token name must contain 1 to 120 characters")
        allowed = {"workspace:read", "workspace:write", "agent:run", "router:read", "router:write", "core:admin"}
        normalized = sorted(set(scopes))
        if not normalized or any(scope not in allowed for scope in normalized):
            raise TokenError("One or more token scopes are invalid")
        if expires_in_days is not None and not 1 <= expires_in_days <= 3650:
            raise TokenError("Token lifetime must be between 1 and 3650 days")

        token = self.PREFIX + secrets.token_urlsafe(36)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=expires_in_days) if expires_in_days is not None else None
        with self._connect() as db:
            cursor = db.execute(
                """INSERT INTO amo_tokens(token_hash,token_hint,name,owner_id,scopes,created_at,expires_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    self._hash(token),
                    token[:18] + "…",
                    clean_name,
                    owner_id,
                    " ".join(normalized),
                    now.isoformat(),
                    expires_at.isoformat() if expires_at else None,
                ),
            )
        return {
            "id": cursor.lastrowid,
            "token": token,
            "token_hint": token[:18] + "…",
            "name": clean_name,
            "scopes": normalized,
            "expires_at": expires_at.isoformat() if expires_at else None,
        }

    def verify(self, token: str, required_scope: str | None = None) -> dict | None:
        if not token.startswith(self.PREFIX):
            return None
        with self._connect() as db:
            row = db.execute("SELECT * FROM amo_tokens WHERE token_hash=?", (self._hash(token),)).fetchone()
            if not row or row["revoked_at"]:
                return None
            if row["expires_at"] and datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
                return None
            scopes = row["scopes"].split()
            if required_scope and required_scope not in scopes and "core:admin" not in scopes:
                return None
            db.execute(
                "UPDATE amo_tokens SET last_used_at=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), row["id"]),
            )
        result = dict(row)
        result["scopes"] = scopes
        result.pop("token_hash", None)
        return result

    def list_for_owner(self, owner_id: int) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT id,token_hint,name,owner_id,scopes,created_at,expires_at,last_used_at,revoked_at
                   FROM amo_tokens WHERE owner_id=? ORDER BY id DESC""",
                (owner_id,),
            ).fetchall()
        return [{**dict(row), "scopes": row["scopes"].split()} for row in rows]

    def revoke(self, token_id: int, owner_id: int) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE amo_tokens SET revoked_at=? WHERE id=? AND owner_id=? AND revoked_at IS NULL",
                (datetime.now(timezone.utc).isoformat(), token_id, owner_id),
            )
        return bool(cursor.rowcount)
