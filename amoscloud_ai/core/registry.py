from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


class ServiceRegistry:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS core_services (
                    name TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    last_seen TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    def register(self, name: str, kind: str, endpoint: str, metadata: str = "{}") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute(
                """INSERT INTO core_services(name,kind,endpoint,metadata,last_seen,enabled)
                   VALUES(?,?,?,?,?,1)
                   ON CONFLICT(name) DO UPDATE SET kind=excluded.kind,endpoint=excluded.endpoint,
                   metadata=excluded.metadata,last_seen=excluded.last_seen,enabled=1""",
                (name.strip(), kind.strip(), endpoint.strip(), metadata, now),
            )

    def heartbeat(self, name: str) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE core_services SET last_seen=? WHERE name=?",
                (datetime.now(timezone.utc).isoformat(), name.strip()),
            )
        return bool(cursor.rowcount)

    def list(self, stale_after_seconds: int = 90) -> list[dict]:
        threshold = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
        with self._connect() as db:
            rows = db.execute("SELECT * FROM core_services ORDER BY name").fetchall()
        result: list[dict] = []
        for row in rows:
            item = dict(row)
            try:
                seen = datetime.fromisoformat(item["last_seen"])
                healthy = seen >= threshold
            except ValueError:
                healthy = False
            item["healthy"] = bool(item["enabled"] and healthy)
            item["enabled"] = bool(item["enabled"])
            result.append(item)
        return result

    def resolve(self, name: str) -> str | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT endpoint FROM core_services WHERE name=? AND enabled=1",
                (name.strip(),),
            ).fetchone()
        return str(row["endpoint"]) if row else None

    def remove(self, name: str) -> bool:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM core_services WHERE name=?", (name.strip(),))
        return bool(cursor.rowcount)
