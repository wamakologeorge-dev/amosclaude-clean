"""Production autonomy supervisor for safe, resumable Amosclaud operation."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

TERMINAL = {"completed", "failed", "blocked", "cancelled"}
RISKY = {"write_files", "commit", "pull_request", "deploy", "rotate_secret", "delete"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Capability:
    name: str
    description: str
    risk: str = "read"
    requires_approval: bool = False
    enabled: bool = True


@dataclass
class Mission:
    id: str
    objective: str
    status: str = "queued"
    phase: str = "receive"
    progress: int = 0
    attempts: int = 0
    max_attempts: int = 3
    lease_owner: str | None = None
    lease_until: str | None = None
    checkpoint: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    blocker: str | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


class AutonomySupervisor:
    """Coordinates heartbeats, leases, checkpoints, approvals, retries and shutdown."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or os.getenv("AMOSCLAUD_AUTONOMY_DB", "/data/autonomy-supervisor.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.capabilities = self._default_capabilities()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    def _ensure_schema(self) -> None:
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS autonomy_missions(
              id TEXT PRIMARY KEY, objective TEXT NOT NULL, status TEXT NOT NULL,
              phase TEXT NOT NULL, progress INTEGER NOT NULL, attempts INTEGER NOT NULL,
              max_attempts INTEGER NOT NULL, lease_owner TEXT, lease_until TEXT,
              checkpoint_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
              blocker TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS autonomy_approvals(
              id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, capability TEXT NOT NULL,
              status TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL,
              decided_at TEXT, FOREIGN KEY(mission_id) REFERENCES autonomy_missions(id)
            );
            CREATE TABLE IF NOT EXISTS autonomy_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT, mission_id TEXT, event TEXT NOT NULL,
              payload_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS autonomy_heartbeat(
              supervisor_id TEXT PRIMARY KEY, state TEXT NOT NULL, last_seen_at TEXT NOT NULL
            );
            """)

    @staticmethod
    def _default_capabilities() -> dict[str, Capability]:
        items = [
            Capability("inspect", "Read repository and runtime evidence"),
            Capability("plan", "Create bounded engineering plans"),
            Capability("test", "Run approved focused verification"),
            Capability("write_files", "Modify workspace files", "write", True),
            Capability("commit", "Create source-control commits", "write", True),
            Capability("pull_request", "Open a reviewable pull request", "write", True),
            Capability("deploy", "Deploy a verified release", "critical", True),
            Capability("rotate_secret", "Rotate platform credentials", "critical", True),
            Capability("delete", "Delete data or resources", "critical", True, False),
        ]
        return {item.name: item for item in items}

    def create_mission(self, objective: str, max_attempts: int = 3) -> Mission:
        mission = Mission("mission_" + uuid.uuid4().hex, objective.strip(), max_attempts=max(1, min(max_attempts, 5)))
        if not mission.objective:
            raise ValueError("Mission objective is required")
        self._save(mission)
        self._event(mission.id, "mission.created", {"objective": mission.objective})
        return mission

    def claim(self, mission_id: str, worker: str, lease_seconds: int = 60) -> Mission:
        mission = self.get(mission_id)
        if mission.status in TERMINAL:
            return mission
        now = datetime.now(timezone.utc)
        if mission.lease_until and datetime.fromisoformat(mission.lease_until) > now and mission.lease_owner != worker:
            raise RuntimeError("Mission already has an active worker lease")
        mission.lease_owner = worker
        mission.lease_until = (now + timedelta(seconds=max(10, min(lease_seconds, 300)))).isoformat()
        mission.status = "running"
        mission.updated_at = _now()
        self._save(mission)
        self._event(mission.id, "mission.claimed", {"worker": worker})
        return mission

    def checkpoint(self, mission_id: str, phase: str, progress: int, data: dict[str, Any] | None = None, evidence: list[str] | None = None) -> Mission:
        mission = self.get(mission_id)
        mission.phase = phase
        mission.progress = max(mission.progress, min(max(progress, 0), 100))
        mission.checkpoint = dict(data or {})
        mission.evidence.extend((evidence or [])[:50])
        mission.updated_at = _now()
        self._save(mission)
        self._event(mission.id, "mission.checkpoint", {"phase": phase, "progress": mission.progress})
        return mission

    def request_approval(self, mission_id: str, capability: str, reason: str) -> dict[str, str]:
        item = self.capabilities.get(capability)
        if not item or not item.enabled:
            raise PermissionError(f"Capability unavailable: {capability}")
        approval_id = "approval_" + uuid.uuid4().hex
        status = "approved" if not item.requires_approval else "pending"
        with self._connect() as db:
            db.execute("INSERT INTO autonomy_approvals VALUES (?,?,?,?,?,?,NULL)", (approval_id, mission_id, capability, status, reason[:500], _now()))
        return {"id": approval_id, "status": status, "capability": capability}

    def decide_approval(self, approval_id: str, approved: bool) -> dict[str, str]:
        status = "approved" if approved else "denied"
        with self._connect() as db:
            row = db.execute("SELECT * FROM autonomy_approvals WHERE id=?", (approval_id,)).fetchone()
            if not row:
                raise KeyError("Approval not found")
            db.execute("UPDATE autonomy_approvals SET status=?,decided_at=? WHERE id=?", (status, _now(), approval_id))
        self._event(row["mission_id"], "approval.decided", {"approval_id": approval_id, "status": status})
        return {"id": approval_id, "status": status}

    def finish(self, mission_id: str, status: str, blocker: str | None = None) -> Mission:
        if status not in TERMINAL:
            raise ValueError("Final status must be terminal")
        mission = self.get(mission_id)
        mission.status = status
        mission.progress = 100 if status == "completed" else mission.progress
        mission.blocker = blocker
        mission.lease_owner = None
        mission.lease_until = None
        mission.updated_at = _now()
        self._save(mission)
        self._event(mission.id, "mission.finished", {"status": status, "blocker": blocker})
        return mission

    def fail_or_retry(self, mission_id: str, error: str) -> Mission:
        mission = self.get(mission_id)
        mission.attempts += 1
        mission.blocker = error[:1000]
        mission.lease_owner = None
        mission.lease_until = None
        mission.status = "queued" if mission.attempts < mission.max_attempts else "failed"
        mission.updated_at = _now()
        self._save(mission)
        self._event(mission.id, "mission.retry" if mission.status == "queued" else "mission.failed", {"attempts": mission.attempts, "error": mission.blocker})
        return mission

    def heartbeat(self, supervisor_id: str = "autonomous-core", state: str = "ready") -> dict[str, str]:
        stamp = _now()
        with self._connect() as db:
            db.execute("INSERT INTO autonomy_heartbeat VALUES (?,?,?) ON CONFLICT(supervisor_id) DO UPDATE SET state=excluded.state,last_seen_at=excluded.last_seen_at", (supervisor_id, state, stamp))
        return {"supervisor_id": supervisor_id, "state": state, "last_seen_at": stamp}

    def readiness(self) -> dict[str, Any]:
        with self._connect() as db:
            heartbeat = db.execute("SELECT * FROM autonomy_heartbeat ORDER BY last_seen_at DESC LIMIT 1").fetchone()
            counts = {row["status"]: row["count"] for row in db.execute("SELECT status,COUNT(*) count FROM autonomy_missions GROUP BY status")}
            pending = db.execute("SELECT COUNT(*) count FROM autonomy_approvals WHERE status='pending'").fetchone()["count"]
        return {
            "status": "ready" if heartbeat else "starting",
            "heartbeat": dict(heartbeat) if heartbeat else None,
            "missions": counts,
            "pending_approvals": pending,
            "capabilities": [asdict(item) for item in self.capabilities.values()],
            "safety": {"bounded_retries": True, "resumable_checkpoints": True, "leases": True, "human_approval_for_risky_actions": True, "truthful_terminal_states": sorted(TERMINAL)},
        }

    def get(self, mission_id: str) -> Mission:
        with self._connect() as db:
            row = db.execute("SELECT * FROM autonomy_missions WHERE id=?", (mission_id,)).fetchone()
        if not row:
            raise KeyError("Mission not found")
        return Mission(row["id"], row["objective"], row["status"], row["phase"], row["progress"], row["attempts"], row["max_attempts"], row["lease_owner"], row["lease_until"], json.loads(row["checkpoint_json"]), json.loads(row["evidence_json"]), row["blocker"], row["created_at"], row["updated_at"])

    def list_missions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT id FROM autonomy_missions ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
        return [asdict(self.get(row["id"])) for row in rows]

    def _save(self, mission: Mission) -> None:
        with self._connect() as db:
            db.execute("""INSERT INTO autonomy_missions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET status=excluded.status,phase=excluded.phase,progress=excluded.progress,attempts=excluded.attempts,max_attempts=excluded.max_attempts,lease_owner=excluded.lease_owner,lease_until=excluded.lease_until,checkpoint_json=excluded.checkpoint_json,evidence_json=excluded.evidence_json,blocker=excluded.blocker,updated_at=excluded.updated_at""",
            (mission.id, mission.objective, mission.status, mission.phase, mission.progress, mission.attempts, mission.max_attempts, mission.lease_owner, mission.lease_until, json.dumps(mission.checkpoint), json.dumps(mission.evidence), mission.blocker, mission.created_at, mission.updated_at))

    def _event(self, mission_id: str | None, event: str, payload: dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO autonomy_events(mission_id,event,payload_json,created_at) VALUES (?,?,?,?)", (mission_id, event, json.dumps(payload), _now()))
