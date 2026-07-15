"""Doctor Medical travel bridge: Amosclaud → Railway runtime → GitHub.

A detected platform injury is mirrored to GitHub as an issue and then queued on
an isolated Autonomous repository path. The main Autonomous Agent receives the
repair task, creates a branch/PR, verifies the treatment, and reports evidence
back through the Doctor Medical dashboard.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.admin import _admin_user
from amoscloud_ai.api.routes.doctor_medical import _db, _event, _now, _row
from amoscloud_ai.api.routes.pr_tasks import queue_task
from amoscloud_ai.models import RepositoryTaskRequest
from amoscloud_ai.logger import log

router = APIRouter(prefix="/doctor-travel", tags=["doctor-medical-travel"])
_REPOSITORY = os.getenv("AMOSCLAUD_AGENT_REPOSITORY", "wamakologeorge-dev/amosclaude-clean").strip()
_AUTO = os.getenv("AMOSCLAUD_DOCTOR_AUTO_TRAVEL", "true").strip().lower() in {"1", "true", "yes", "on"}
_POLL_SECONDS = max(10, int(os.getenv("AMOSCLAUD_DOCTOR_TRAVEL_POLL_SECONDS", "30")))
_STARTED = False
_START_LOCK = threading.Lock()


class TravelRequest(BaseModel):
    force: bool = False
    source_time: str = Field(default="", max_length=80)


def _ensure_table(db: sqlite3.Connection) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS doctor_travel (
            issue_id TEXT PRIMARY KEY,
            repository TEXT NOT NULL,
            railway_service TEXT NOT NULL DEFAULT '',
            railway_environment TEXT NOT NULL DEFAULT '',
            railway_deployment TEXT NOT NULL DEFAULT '',
            source_time TEXT NOT NULL DEFAULT '',
            github_issue_number INTEGER,
            github_issue_url TEXT NOT NULL DEFAULT '',
            repository_task_id TEXT NOT NULL DEFAULT '',
            repository_branch TEXT NOT NULL DEFAULT '',
            repository_status_url TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            error_detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    db.commit()


def _provenance(source_time: str = "") -> dict[str, str]:
    return {
        "origin": "amosclaud.com",
        "transport": "railway.com",
        "destination": "github.com",
        "repository": _REPOSITORY,
        "source_time": source_time or datetime.now(timezone.utc).isoformat(),
        "railway_service": os.getenv("RAILWAY_SERVICE_NAME", ""),
        "railway_environment": os.getenv("RAILWAY_ENVIRONMENT_NAME", ""),
        "railway_deployment": os.getenv("RAILWAY_DEPLOYMENT_ID", ""),
        "railway_project": os.getenv("RAILWAY_PROJECT_NAME", ""),
    }


def _github_headers() -> dict[str, str]:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not configured on Railway.")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _create_github_issue(issue: dict[str, Any], provenance: dict[str, str]) -> tuple[int, str]:
    title = f"[Doctor Medical] {issue['title']}"
    body = f"""## Amosclaud platform injury

This issue was created automatically by **Amosclaud Doctor Medical**.

### Travel path

```text
Amosclaud.com Autonomous
  → Railway runtime health
  → Doctor Medical issue router
  → GitHub repository issue
  → isolated Autonomous repair branch
  → pull request + verified result
  → Amosclaud issue mirror
```

### Source

- Origin: `{provenance['origin']}`
- Runtime transport: `{provenance['transport']}`
- Repository: `{provenance['repository']}`
- Source time: `{provenance['source_time']}`
- Railway service: `{provenance['railway_service'] or 'unknown'}`
- Railway environment: `{provenance['railway_environment'] or 'unknown'}`
- Railway deployment: `{provenance['railway_deployment'] or 'unknown'}`
- Doctor issue ID: `{issue['id']}`

### Injury evidence

- Severity: `{issue['severity']}`
- Source engine: `{issue['source']}`
- Assigned engine: `{issue['assigned_engine'] or 'pending'}`
- Endpoint: `{issue['endpoint'] or 'not supplied'}`
- Error type: `{issue['error_type'] or 'not supplied'}`

```text
{issue['safe_detail'] or 'No additional safe detail supplied.'}
```

### Treatment policy

- Preserve users, passwords, passkeys, sessions, secrets, and production databases.
- Apply the smallest safe fix in an isolated branch.
- Run focused verification and report changed files and evidence.
- Do not report healed until the main Autonomous Agent verifies the result.
"""
    url = f"https://api.github.com/repos/{_REPOSITORY}/issues"
    with httpx.Client(timeout=20) as client:
        response = client.post(url, headers=_github_headers(), json={"title": title, "body": body, "labels": ["doctor-medical", "self-heal"]})
    if response.status_code == 422:
        # Labels may not exist yet; retry without labels.
        with httpx.Client(timeout=20) as client:
            response = client.post(url, headers=_github_headers(), json={"title": title, "body": body})
    response.raise_for_status()
    payload = response.json()
    return int(payload["number"]), str(payload["html_url"])


def _repository_objective(issue: dict[str, Any], github_issue_number: int, provenance: dict[str, str]) -> str:
    return f"""Doctor Medical cross-platform repair.

Origin: Amosclaud.com Autonomous
Runtime transport: Railway.com
GitHub issue: #{github_issue_number}
Doctor issue: {issue['id']}
Source time: {provenance['source_time']}

Diagnose and repair this platform injury:
{issue['title']}
Endpoint: {issue['endpoint'] or 'not supplied'}
Error: {issue['error_type'] or 'not supplied'}
Evidence: {issue['safe_detail'] or 'No additional safe detail supplied.'}
Assigned engine: {issue['assigned_engine'] or 'platform-diagnostic-engine'}
Treatment plan: {issue['repair_plan'] or 'Reproduce, isolate, apply the smallest safe fix, and verify.'}

Work on an isolated branch. Preserve all users, passwords, passkeys, sessions,
secrets, and production databases. Run focused tests. Create a pull request that
links GitHub issue #{github_issue_number}. Report elapsed time, changed files,
what was fixed, what remains, and verification evidence. Do not claim success
until the tests prove the treatment worked.
"""


def dispatch_issue(issue_id: str, *, force: bool = False, source_time: str = "") -> dict[str, Any]:
    issue = _row(issue_id)
    provenance = _provenance(source_time)
    with _db() as db:
        _ensure_table(db)
        existing = db.execute("SELECT * FROM doctor_travel WHERE issue_id=?", (issue_id,)).fetchone()
        if existing and not force:
            return dict(existing)
        if existing and force:
            db.execute("DELETE FROM doctor_travel WHERE issue_id=?", (issue_id,))
        now = _now()
        db.execute(
            """INSERT INTO doctor_travel(
                issue_id,repository,railway_service,railway_environment,railway_deployment,
                source_time,status,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,'travelling',?,?)""",
            (
                issue_id, _REPOSITORY, provenance["railway_service"], provenance["railway_environment"],
                provenance["railway_deployment"], provenance["source_time"], now, now,
            ),
        )
        _event(db, issue_id, "travel", "started", "Issue left Amosclaud.com and entered the Railway → GitHub repair path.", provenance)
        db.commit()

    try:
        number, issue_url = _create_github_issue(issue, provenance)
        objective = _repository_objective(issue, number, provenance)
        task = queue_task(RepositoryTaskRequest(objective=objective, base_branch="main"))
        with _db() as db:
            _ensure_table(db)
            db.execute(
                """UPDATE doctor_travel SET github_issue_number=?,github_issue_url=?,repository_task_id=?,
                    repository_branch=?,repository_status_url=?,status='repository-agent-queued',updated_at=? WHERE issue_id=?""",
                (number, issue_url, task.task_id, task.branch, f"/api/v1/agent/github/travel/{task.task_id}", _now(), issue_id),
            )
            db.execute("UPDATE doctor_issues SET status='repository-agent-queued',updated_at=? WHERE id=?", (_now(), issue_id))
            _event(
                db, issue_id, "github-issue", "created",
                f"GitHub issue #{number} created and a separate Autonomous repository path was queued.",
                {"github_issue_url": issue_url, "task_id": task.task_id, "branch": task.branch},
            )
            db.commit()
        return travel_status(issue_id)
    except Exception as exc:
        log.exception("Doctor travel failed for %s", issue_id)
        with _db() as db:
            _ensure_table(db)
            db.execute("UPDATE doctor_travel SET status='failed',error_detail=?,updated_at=? WHERE issue_id=?", (f"{type(exc).__name__}: {exc}", _now(), issue_id))
            _event(db, issue_id, "travel", "failed", "Cross-platform travel stopped safely.", {"error_type": type(exc).__name__})
            db.commit()
        return travel_status(issue_id)


def travel_status(issue_id: str) -> dict[str, Any]:
    with _db() as db:
        _ensure_table(db)
        row = db.execute("SELECT * FROM doctor_travel WHERE issue_id=?", (issue_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Doctor travel record not found")
        return dict(row)


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


@router.on_event("startup")
def _startup() -> None:
    start_auto_travel_worker()


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
        counts = {row["status"]: row["count"] for row in db.execute("SELECT status,COUNT(*) AS count FROM doctor_travel GROUP BY status").fetchall()}
    return {
        "service": "Doctor Medical Cross-Platform Travel",
        "ready": bool(os.getenv("GITHUB_TOKEN", "").strip()),
        "automatic": _AUTO,
        "poll_seconds": _POLL_SECONDS,
        "repository": _REPOSITORY,
        "path": ["amosclaud.com", "railway.com", "github.com", _REPOSITORY],
        "status_counts": counts,
    }
