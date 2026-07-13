from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class VaultError(RuntimeError):
    pass


class AmosclaudVault:
    """Small encrypted settings vault owned by Amosclaud itself."""

    def __init__(self, db_path: Path | None = None, master_key: str | None = None):
        self.db_path = db_path or Path(os.getenv("AMOSCLAUD_CORE_DB", "/data/amosclaud-core.db"))
        raw_key = master_key or os.getenv("AMOSCLAUD_MASTER_KEY", "")
        if not raw_key:
            raise VaultError("AMOSCLAUD_MASTER_KEY is required")
        digest = hashlib.sha256(raw_key.encode("utf-8")).digest()
        self._cipher = Fernet(base64.urlsafe_b64encode(digest))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS core_settings (
                    name TEXT PRIMARY KEY,
                    encrypted_value BLOB NOT NULL,
                    is_secret INTEGER NOT NULL DEFAULT 1,
                    updated_by INTEGER,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS core_settings_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor_id INTEGER,
                    created_at TEXT NOT NULL
                );
                """
            )

    def set(self, name: str, value: str, *, secret: bool = True, actor_id: int | None = None) -> None:
        name = name.strip().upper()
        if not name or len(name) > 120:
            raise VaultError("Invalid setting name")
        encrypted = self._cipher.encrypt(value.encode("utf-8"))
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute(
                """INSERT INTO core_settings(name,encrypted_value,is_secret,updated_by,updated_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(name) DO UPDATE SET encrypted_value=excluded.encrypted_value,
                   is_secret=excluded.is_secret,updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
                (name, encrypted, int(secret), actor_id, now),
            )
            db.execute(
                "INSERT INTO core_settings_audit(name,action,actor_id,created_at) VALUES(?,?,?,?)",
                (name, "set", actor_id, now),
            )

    def get(self, name: str) -> str | None:
        with self._connect() as db:
            row = db.execute("SELECT encrypted_value FROM core_settings WHERE name=?", (name.strip().upper(),)).fetchone()
        if not row:
            return None
        try:
            return self._cipher.decrypt(row["encrypted_value"]).decode("utf-8")
        except InvalidToken as exc:
            raise VaultError("Stored value cannot be decrypted with this master key") from exc

    def list_masked(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT name,is_secret,updated_by,updated_at FROM core_settings ORDER BY name"
            ).fetchall()
        return [
            {
                "name": row["name"],
                "value": "••••••••" if row["is_secret"] else self.get(row["name"]),
                "is_secret": bool(row["is_secret"]),
                "updated_by": row["updated_by"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def delete(self, name: str, *, actor_id: int | None = None) -> bool:
        normalized = name.strip().upper()
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            cursor = db.execute("DELETE FROM core_settings WHERE name=?", (normalized,))
            if cursor.rowcount:
                db.execute(
                    "INSERT INTO core_settings_audit(name,action,actor_id,created_at) VALUES(?,?,?,?)",
                    (normalized, "delete", actor_id, now),
                )
        return bool(cursor.rowcount)
