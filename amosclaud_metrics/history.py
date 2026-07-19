from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


class HistoryStore:
    def __init__(self, path: Path, retention_days: int = 7):
        self.path = path
        self.retention_days = max(1, retention_days)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS metric_snapshots (
                    collected_at REAL PRIMARY KEY,
                    status TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL
                )""")
            db.commit()

    def record(self, snapshot: dict) -> None:
        self.initialize()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.retention_days)).timestamp()
        with sqlite3.connect(self.path, timeout=3) as db:
            db.execute(
                "INSERT OR REPLACE INTO metric_snapshots VALUES (?,?,?)",
                (
                    snapshot["collected_at_unix"],
                    snapshot["status"],
                    json.dumps(snapshot, separators=(",", ":")),
                ),
            )
            db.execute("DELETE FROM metric_snapshots WHERE collected_at < ?", (cutoff,))
            db.commit()

    def recent(self, limit: int = 100) -> list[dict]:
        self.initialize()
        with sqlite3.connect(self.path) as db:
            rows = db.execute(
                "SELECT snapshot_json FROM metric_snapshots ORDER BY collected_at DESC LIMIT ?",
                (min(max(limit, 1), 1000),),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]
