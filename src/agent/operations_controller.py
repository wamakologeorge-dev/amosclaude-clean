"""Track Autonomous jobs and truthful outcomes."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentOperationsController:
    def __init__(self, runner: Callable[..., dict[str, Any]], db_path: str | None = None) -> None:
        self.runner = runner
        self.db_path = Path(db_path or os.getenv("AMOSCLAUD_AGENT_OPS_DB", "/data/agent-operations.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS agent_jobs (id TEXT PRIMARY KEY, objective TEXT, mode TEXT, agent TEXT, status TEXT, progress INTEGER, blocker TEXT, evidence TEXT, result TEXT, created_at TEXT, started_at TEXT, finished_at TEXT)")

    def submit(self, objective: str, mode: str = "plan", authorized_writes: bool = False, workspace: str = ".") -> dict[str, Any]:
        job_id = "agentjob_" + uuid.uuid4().hex
        agent = self._agent(mode)
        created = utc_now()
        with sqlite3.connect(self.db_path) as db:
            db.execute("INSERT INTO agent_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (job_id, objective, mode, agent, "running", 10, None, "{}", None, created, created, None))
        try:
            result = self.runner(objective=objective, mode=mode, authorized_writes=authorized_writes, workspace=workspace)
            status = self._truthful_status(result, authorized_writes)
            evidence = {
                "changed_files": result.get("changed_files", []),
                "checks": result.get("checks", []),
                "events": result.get("events", []),
            }
            blocker = result.get("blocker")
            with sqlite3.connect(self.db_path) as db:
                db.execute("UPDATE agent_jobs SET status=?,progress=100,blocker=?,evidence=?,result=?,finished_at=? WHERE id=?", (status, blocker, json.dumps(evidence), json.dumps(result), utc_now(), job_id))
        except Exception as exc:
            with sqlite3.connect(self.db_path) as db:
                db.execute("UPDATE agent_jobs SET status='failed',progress=100,blocker=?,finished_at=? WHERE id=?", (f"{type(exc).__name__}: {exc}", utc_now(), job_id))
        return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM agent_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return {"id": job_id, "status": "missing"}
        item = dict(row)
        item["evidence"] = json.loads(item["evidence"] or "{}")
        item["result"] = json.loads(item["result"] or "null")
        return item

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM agent_jobs ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
        jobs = []
        for row in rows:
            item = dict(row)
            item["evidence"] = json.loads(item["evidence"] or "{}")
            item["result"] = json.loads(item["result"] or "null")
            jobs.append(item)
        return jobs

    @staticmethod
    def _agent(mode: str) -> str:
        return {"plan":"agent-3-planner","build":"agent-4-builder","test":"agent-5-verifier","review":"agent-2-evidence","fix":"agent-4-repair","deploy":"agent-5-release","monitor":"agent-1-receiver"}.get(mode, "agent-1-receiver")

    @staticmethod
    def _truthful_status(result: dict[str, Any], authorized: bool) -> str:
        if result.get("status") == "success":
            return "completed"
        if result.get("blocker") and not authorized:
            return "waiting_for_approval"
        if result.get("changed_files"):
            return "partially_completed"
        return "blocked" if result.get("blocker") else "failed"
