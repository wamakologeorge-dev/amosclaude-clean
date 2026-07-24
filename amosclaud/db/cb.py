"""Persistent CB records for ``amosclaud.db.cb``."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DatabaseCB:
    key: str
    value: dict[str, Any]
    version: int = 1


class SQLiteCBStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS amosclaud_cb (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, version INTEGER NOT NULL)"
            )
            db.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def put(self, record: DatabaseCB) -> None:
        if not record.key.strip():
            raise ValueError("record key is required")
        encoded = json.dumps(record.value, sort_keys=True, separators=(",", ":"))
        with self._connect() as db:
            db.execute(
                "INSERT INTO amosclaud_cb(key,value_json,version) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, version=excluded.version",
                (record.key, encoded, record.version),
            )
            db.commit()

    def get(self, key: str) -> DatabaseCB | None:
        with self._connect() as db:
            row = db.execute("SELECT key,value_json,version FROM amosclaud_cb WHERE key=?", (key,)).fetchone()
        return DatabaseCB(row[0], json.loads(row[1]), row[2]) if row else None

    def delete(self, key: str) -> bool:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM amosclaud_cb WHERE key=?", (key,))
            db.commit()
        return cursor.rowcount == 1
