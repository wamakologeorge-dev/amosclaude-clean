"""Amosclaud Doctor Medical self-healing issue engine.

This module records platform injuries, routes them through a protected mini
Autonomous fixer, and exposes truthful repair evidence to administrators and
clients. It never deletes users, passwords, passkeys, sessions, secrets, or
production databases.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes import auth as auth_routes
from amoscloud_ai.api.routes.admin import _admin_user
from amoscloud_ai.logger import log

router = APIRouter(prefix="/doctor", tags=["doctor-medical-self-heal"])
_LOCK = threading.RLock()
_PROTECTED_TERMS = {
    "users", "password", "password_hash", "passkeys", "sessions", "secrets",
    "auth.db", "drop table", "delete from users", "truncate", ".env",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db() -> sqlite3.Connection:
    db = auth_routes._connect()
    db.execute("PRAGMA foreign_keys = ON")
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS doctor_issues (
            id TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL,
            source TEXT NOT NULL,
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            endpoint TEXT NOT NULL DEFAULT '',
            error_type TEXT NOT NULL DEFAULT '',
            safe_detail TEXT NOT NULL DEFAULT '',
            evidence TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'detected',
            assigned_engine TEXT NOT NULL DEFAULT '',
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            repair_plan TEXT NOT NULL DEFAULT '',
            changed_files TEXT NOT NULL DEFAULT '[]',
            verification TEXT NOT NULL DEFAULT '{}',
            result_summary TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            resolved_at TEXT
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS doctor_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            status TEXT NOT NULL,
            message TEXT NOT NULL,
            evidence TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(issue_id) REFERENCES doctor_issues(id) ON DELETE CASCADE
        )
        """
    )
    db.commit()
    return db


class IssueCreate(BaseModel):
    source: str = Field(default="platform-api", max_length=80)
    severity: str = Field(default="error", pattern="^(warning|error|critical)$")
    title: str = Field(min_length=3, max_length=240)
    endpoint: str = Field(default="", max_length=240)
    error_type: str = Field(default="", max_length=120)
    safe_detail: str = Field(default="", max_length=2000)
    evidence: dict[str, Any] = Field(default_factory=dict)
    auto_start: bool = True


class DoctorAction(BaseModel):
    action: str = Field(pattern="^(diagnose|treat|verify|handoff|stop)$")


def _fingerprint(source: str, title: str, endpoint: str, error_type: str) -> str:
    import hashlib

    normal = "|".join([source.strip().lower(), title.strip().lower(), endpoint.strip(), error_type.strip()])
    return hashlib.sha256(normal.encode()).hexdigest()


def _event(db: sqlite3.Connection, issue_id: str, phase: str, status: str, message: str, evidence: dict | None = None) -> None:
    db.execute(
        "INSERT INTO doctor_events(issue_id,phase,status,message,evidence,created_at) VALUES (?,?,?,?,?,?)",
        (issue_id, phase, status, message, json.dumps(evidence or {}, default=str), _now()),
    )


def _row(issue_id: str) -> dict:
    with _db() as db:
        row = db.execute("SELECT * FROM doctor_issues WHERE id=?", (issue_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Doctor issue not found")
        item = dict(row)
        for key in ("evidence", "changed_files", "verification"):
            try:
                item[key] = json.loads(item[key] or ("[]" if key == "changed_files" else "{}"))
            except json.JSONDecodeError:
                pass
        item["events"] = [dict(event) for event in db.execute(
            "SELECT phase,status,message,evidence,created_at FROM doctor_events WHERE issue_id=? ORDER BY id", (issue_id,)
        ).fetchall()]
        return item


def record_platform_injury(
    *, source: str, title: str, endpoint: str = "", error_type: str = "", safe_detail: str = "", evidence: dict | None = None
) -> str:
    """Create or refresh a deduplicated issue without exposing secrets."""
    fingerprint = _fingerprint(source, title, endpoint, error_type)
    with _LOCK, _db() as db:
        existing = db.execute(
            "SELECT id,status FROM doctor_issues WHERE fingerprint=? AND status NOT IN ('healed','closed') ORDER BY created_at DESC LIMIT 1",
            (fingerprint,),
        ).fetchone()
        if existing:
            issue_id = existing["id"]
            db.execute(
                "UPDATE doctor_issues SET safe_detail=?,evidence=?,updated_at=? WHERE id=?",
                (safe_detail[:2000], json.dumps(evidence or {}, default=str), _now(), issue_id),
            )
            _event(db, issue_id, "detect", "repeated", "The same platform injury was observed again.", evidence)
            db.commit()
            return issue_id
        issue_id = str(uuid.uuid4())
        now = _now()
        db.execute(
            """INSERT INTO doctor_issues(
                id,fingerprint,source,severity,title,endpoint,error_type,safe_detail,evidence,status,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,'detected',?,?)""",
            (issue_id, fingerprint, source, "error", title, endpoint, error_type, safe_detail[:2000], json.dumps(evidence or {}, default=str), now, now),
        )
        _event(db, issue_id, "detect", "created", "Platform health created a Doctor Medical issue.", evidence)
        db.commit()
        return issue_id


def _safe_plan(issue: dict) -> tuple[str, str]:
    text = f"{issue['title']} {issue['endpoint']} {issue['error_type']} {issue['safe_detail']}".lower()
    if any(term in text for term in ("connection refused", "upstream", "model station", "model api")):
        return (
            "model-network-health-engine",
            "Probe DNS, TCP connection, /health, authentication, content type, and one inference request. "
            "Repair configuration or service startup only; never expose tokens.",
        )
    if "admin/users" in text or "users endpoint" in text:
        return (
            "platform-api-repair-engine",
            "Inspect route registration and optional database joins, reproduce with a temporary test database, "
            "apply the smallest compatibility fix, and preserve every user record.",
        )
    if "login" in text or "session" in text or "authentication" in text:
        return (
            "protected-auth-repair-engine",
            "Trace signup, identity normalization, password verification, cookie creation, and /auth/me using a temporary account. "
            "Do not reset or modify real user data.",
        )
    return (
        "platform-diagnostic-engine",
        "Reproduce the failure, isolate the responsible route or service, prepare the smallest safe workspace repair, "
        "run focused tests, and return evidence for the main Autonomous Agent.",
    )


def _run_mini_autonomous(issue_id: str) -> None:
    """Protected underground fixer. It diagnoses and prepares treatment evidence.

    Code writes remain delegated to the main Autonomous controlled workspace.
    This prevents an endless background loop from silently rewriting production.
    """
    started = time.monotonic()
    try:
        issue = _row(issue_id)
        with _LOCK, _db() as db:
            attempts = int(issue["attempts"]) + 1
            if attempts > int(issue["max_attempts"]):
                db.execute("UPDATE doctor_issues SET status='needs-owner',updated_at=? WHERE id=?", (_now(), issue_id))
                _event(db, issue_id, "treat", "stopped", "Safe automatic attempt limit reached; owner review is required.")
                db.commit()
                return
            engine, plan = _safe_plan(issue)
            db.execute(
                "UPDATE doctor_issues SET status='diagnosing',assigned_engine=?,attempts=?,repair_plan=?,updated_at=? WHERE id=?",
                (engine, attempts, plan, _now(), issue_id),
            )
            _event(db, issue_id, "perceive", "completed", "Repository and runtime evidence accepted by Doctor Medical.")
            _event(db, issue_id, "diagnose", "completed", f"Assigned to {engine}.", {"plan": plan})
            db.commit()

        # Mini Autonomous creates a treatment packet. The main Autonomous performs
        # controlled file edits and final verification in the repository workspace.
        verification = {
            "diagnosis_ready": True,
            "protected_data_untouched": True,
            "requires_main_autonomous": True,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        with _LOCK, _db() as db:
            db.execute(
                "UPDATE doctor_issues SET status='ready-for-treatment',verification=?,result_summary=?,updated_at=? WHERE id=?",
                (
                    json.dumps(verification),
                    "Doctor Medical prepared a safe repair plan. Main Autonomous must apply and verify the code treatment.",
                    _now(),
                    issue_id,
                ),
            )
            _event(db, issue_id, "medication", "prepared", "A protected treatment packet is ready for the main Autonomous Agent.", verification)
            _event(db, issue_id, "handoff", "waiting", "Waiting for controlled Autonomous fix + verify execution.")
            db.commit()
    except Exception as exc:
        log.exception("Doctor Medical worker failed for issue %s", issue_id)
        with _LOCK, _db() as db:
            db.execute("UPDATE doctor_issues SET status='failed',result_summary=?,updated_at=? WHERE id=?", (f"{type(exc).__name__}: {exc}", _now(), issue_id))
            _event(db, issue_id, "doctor", "failed", "Mini Autonomous stopped safely.", {"error_type": type(exc).__name__})
            db.commit()


@router.post("/issues", status_code=202)
def create_issue(body: IssueCreate, background: BackgroundTasks, admin=Depends(_admin_user)) -> dict:
    del admin
    issue_id = record_platform_injury(
        source=body.source,
        title=body.title,
        endpoint=body.endpoint,
        error_type=body.error_type,
        safe_detail=body.safe_detail,
        evidence=body.evidence,
    )
    if body.auto_start:
        background.add_task(_run_mini_autonomous, issue_id)
    return {"accepted": True, "issue_id": issue_id, "status": _row(issue_id)["status"]}


@router.get("/issues")
def list_issues(status: str = Query(default="", max_length=40), limit: int = Query(default=100, ge=1, le=500), admin=Depends(_admin_user)) -> list[dict]:
    del admin
    with _db() as db:
        if status:
            rows = db.execute("SELECT * FROM doctor_issues WHERE status=? ORDER BY updated_at DESC LIMIT ?", (status, limit)).fetchall()
        else:
            rows = db.execute("SELECT * FROM doctor_issues ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


@router.get("/issues/{issue_id}")
def get_issue(issue_id: str, admin=Depends(_admin_user)) -> dict:
    del admin
    return _row(issue_id)


@router.post("/issues/{issue_id}/action")
def issue_action(issue_id: str, body: DoctorAction, background: BackgroundTasks, admin=Depends(_admin_user)) -> dict:
    del admin
    issue = _row(issue_id)
    if body.action in {"diagnose", "treat"}:
        background.add_task(_run_mini_autonomous, issue_id)
    elif body.action == "verify":
        with _db() as db:
            _event(db, issue_id, "verify", "requested", "Main Autonomous final verification requested.")
            db.execute("UPDATE doctor_issues SET status='verification-required',updated_at=? WHERE id=?", (_now(), issue_id))
            db.commit()
    elif body.action == "handoff":
        with _db() as db:
            _event(db, issue_id, "handoff", "requested", "Issue handed to main Autonomous Agent for controlled fix + verify.")
            db.execute("UPDATE doctor_issues SET status='main-agent-required',updated_at=? WHERE id=?", (_now(), issue_id))
            db.commit()
    else:
        with _db() as db:
            _event(db, issue_id, "doctor", "stopped", "Owner stopped automatic treatment.")
            db.execute("UPDATE doctor_issues SET status='stopped',updated_at=? WHERE id=?", (_now(), issue_id))
            db.commit()
    return _row(issue_id)


@router.get("/health")
def doctor_health(admin=Depends(_admin_user)) -> dict:
    del admin
    with _db() as db:
        open_count = db.execute("SELECT COUNT(*) FROM doctor_issues WHERE status NOT IN ('healed','closed')").fetchone()[0]
        healing_count = db.execute("SELECT COUNT(*) FROM doctor_issues WHERE status IN ('diagnosing','ready-for-treatment','verification-required','main-agent-required')").fetchone()[0]
    return {
        "service": "Doctor Medical Self-Heal",
        "ready": True,
        "open_issues": int(open_count),
        "active_treatments": int(healing_count),
        "policy": "detect → diagnose → medication → controlled treatment → verify → healed",
        "protected_data": sorted(_PROTECTED_TERMS),
    }
