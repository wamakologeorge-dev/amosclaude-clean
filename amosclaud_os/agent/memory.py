"""Persistent mission and roadmap memory for the Amosclaud Agent."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import DB_PATH
from amosclaud_os.kernel.runtime import AMOSCLAUD_OS_MISSION, AMOSCLAUD_OS_ROADMAP


class OperatorMemory(BaseModel):
    user_id: int
    mission: str
    roadmap: list[str]
    current_focus: str = "Build the Amosclaud OS native engineering foundation"
    updated_at: str

    def as_agent_metadata(self) -> dict[str, object]:
        return {
            "operator_identity": "amosclaud-agent",
            "operator_mission": self.mission,
            "operator_roadmap": self.roadmap,
            "operator_current_focus": self.current_focus,
            "remember_platform_plan": True,
        }


class FocusUpdate(BaseModel):
    current_focus: str = Field(..., min_length=3, max_length=2000)


class OperatorMemoryService:
    def __init__(self, database_path=DB_PATH):
        self.database_path = database_path

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.database_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute(
            """CREATE TABLE IF NOT EXISTS operator_memory (
                   user_id INTEGER PRIMARY KEY,
                   mission TEXT NOT NULL,
                   roadmap_json TEXT NOT NULL,
                   current_focus TEXT NOT NULL,
                   updated_at TEXT NOT NULL,
                   FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
               )"""
        )
        db.commit()
        return db

    def resolve(self, user_id: int) -> OperatorMemory:
        with self._connect() as db:
            row = db.execute("SELECT * FROM operator_memory WHERE user_id=?", (user_id,)).fetchone()
            if not row:
                now = datetime.now(timezone.utc).isoformat()
                db.execute(
                    "INSERT INTO operator_memory(user_id,mission,roadmap_json,current_focus,updated_at) VALUES (?,?,?,?,?)",
                    (user_id, AMOSCLAUD_OS_MISSION, json.dumps(AMOSCLAUD_OS_ROADMAP), "Build the Amosclaud OS native engineering foundation", now),
                )
                db.commit()
                row = db.execute("SELECT * FROM operator_memory WHERE user_id=?", (user_id,)).fetchone()
        return OperatorMemory(
            user_id=user_id,
            mission=row["mission"],
            roadmap=list(json.loads(row["roadmap_json"])),
            current_focus=row["current_focus"],
            updated_at=row["updated_at"],
        )

    def remember_focus(self, user_id: int, focus: str) -> OperatorMemory:
        self.resolve(user_id)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute("UPDATE operator_memory SET current_focus=?,updated_at=? WHERE user_id=?", (focus.strip(), now, user_id))
            db.commit()
        return self.resolve(user_id)
