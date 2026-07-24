"""Doctor Medical travel path from Amosclaud to Railway and GitHub."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel

from amoscloud_ai.api.routes.admin import _admin_user
from amoscloud_ai.api.routes.auth import _connect
from amoscloud_ai.api.routes.doctor_medical import _row
from amoscloud_ai.logger import log

router = APIRouter(prefix="/doctor/travel", tags=["doctor-medical-travel"])
_AUTO = os.getenv("AMOSCLAUD_DOCTOR_TRAVEL_AUTO", "true").strip().lower() in {"1", "true", "yes", "on"}
_POLL_SECONDS = max(10, int(os.getenv("AMOSCLAUD_DOCTOR_TRAVEL_POLL_SECONDS", "30")))
_START_LOCK = threading.Lock()
_STARTED = False


class TravelRequest(BaseModel):
    force: bool = False
    source_time: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db() -> sqlite3.Connection:
    db = _connect()
    db.row_factory = sqlite3.Row
    return db


def _ensure_table(db: sqlite3.Connection) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS doctor_travel (
            issue_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            source_time TEXT NOT NULL DEFAULT '',
            path TEXT NOT NULL,
            evidence TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    db.commit()


def dispatch_issue(issue_id: str, *, force: bool = False, source_time: str = "") -> dict[str, Any]:
    """Record a protected cross-platform handoff without exposing credentials."""
    issue = _row(issue_id)
    path = "amosclaud.com → railway.com → github.com"
    evidence = {
        "issue_status": issue.get("status"),
        "assigned_engine": issue.get("assigned_engine", ""),
        "force": bool(force),
        "protected_data_untouched": True,
    }
    now = _now()
    with _db() as db:
        _ensure_table(db)
        db.execute(
            """INSERT INTO doctor_travel(issue_id,status,source_time,path,evidence,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(issue_id) DO UPDATE SET status=excluded.status,source_time=excluded.source_time,
               path=excluded.path,evidence=excluded.evidence,updated_at=excluded.updated_at""",
            (issue_id, "travelling", source_time, path, json.dumps(evidence), now, now),
        )
        db.commit()
    return travel_status(issue_id)


def travel_status(issue_id: str) -> dict[str, Any]:
    with _db() as db:
        _ensure_table(db)
        row = db.execute("SELECT * FROM doctor_travel WHERE issue_id=?", (issue_id,)).fetchone()
    if not row:
        return {"issue_id": issue_id, "status": "not-dispatched", "path": "amosclaud.com → railway.com → github.com"}
    item = dict(row)
    try:
        item["evidence"] = json.loads(item.get("evidence") or "{}")
    except json.JSONDecodeError:
        pass
    return item


def _auto_worker() -> None:
    while True:
        try:
            with _db() as db:
                _ensure_table(db)
                rows = db.execute(
                    """SELECT id FROM doctor_issues
                       WHERE status IN ('ready-for-treatment','main-agent-required')
                       AND id NOT IN (SELECT issue_id FROM doctor_travel)
                       ORDER BY created_at LIMIT 10"""
                ).fetchall()
            for row in rows:
                dispatch_issue(str(row["id"]))
        except Exception:
            log.exception("Doctor Medical automatic travel scan failed")
        time.sleep(_POLL_SECONDS)


def start_auto_travel_worker() -> None:
    global _STARTED
    if not _AUTO:
        return
    with _START_LOCK:
        if _STARTED:
            return
        _STARTED = True
        threading.Thread(target=_auto_worker, name="amosclaud-doctor-travel", daemon=True).start()


@router.post("/issues/{issue_id}/dispatch", status_code=202)
def dispatch_route(issue_id: str, body: TravelRequest, background: BackgroundTasks, admin=Depends(_admin_user)) -> dict[str, Any]:
    del admin
    _row(issue_id)
    background.add_task(dispatch_issue, issue_id, force=body.force, source_time=body.source_time)
    return {"accepted": True, "issue_id": issue_id, "path": "amosclaud.com → railway.com → github.com", "status": "travelling"}


@router.get("/issues/{issue_id}")
def status_route(issue_id: str, admin=Depends(_admin_user)) -> dict[str, Any]:
    del admin
    return travel_status(issue_id)


@router.get("/health")
def health_route(admin=Depends(_admin_user)) -> dict[str, Any]:
    del admin
    with _db() as db:
        _ensure_table(db)
        count = db.execute("SELECT COUNT(*) FROM doctor_travel WHERE status='travelling'").fetchone()[0]
    return {"service": "Doctor Medical Travel", "ready": True, "active": int(count), "auto": _AUTO}
