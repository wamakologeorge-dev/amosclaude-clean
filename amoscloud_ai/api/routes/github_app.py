"""Inbound GitHub App integration for the Amosclaud platform.

Receives webhook deliveries from the "Amosclaud Platform" GitHub App at
``/api/v1/agent/github/webhook``, verifies their signatures, records every
event into the repository's codex memory volume, and exposes a queryable
event feed so GitHub activity becomes a first-class tool inside the platform.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from amoscloud_ai import codex_memory
from amoscloud_ai.api.routes.agent import _authenticated_user

router = APIRouter(prefix="/agent/github", tags=["github-app"])

HANDLED_EVENTS = {
    "ping",
    "push",
    "pull_request",
    "issues",
    "issue_comment",
    "installation",
    "installation_repositories",
    "check_suite",
    "workflow_run",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _events_db_path() -> Path:
    configured = os.getenv("AMOSCLAUD_GITHUB_EVENTS_DB", "").strip()
    return Path(configured) if configured else Path("./data/github_app_events.db")


def _connect() -> sqlite3.Connection:
    path = _events_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute(
        """CREATE TABLE IF NOT EXISTS github_events (
            id TEXT PRIMARY KEY,
            delivery_id TEXT,
            event TEXT NOT NULL,
            action TEXT,
            repository TEXT,
            sender TEXT,
            summary TEXT NOT NULL,
            received_at TEXT NOT NULL
        )"""
    )
    return db


def _webhook_secret() -> str:
    return os.getenv("GITHUB_APP_WEBHOOK_SECRET", "").strip()


def _production() -> bool:
    return os.getenv("AMOSCLAUD_ENV", "development").lower() in {"production", "prod"}


def _verify_signature(payload: bytes, signature_header: str | None) -> None:
    secret = _webhook_secret()
    if not secret:
        if _production():
            raise HTTPException(
                status_code=503,
                detail="GITHUB_APP_WEBHOOK_SECRET is not configured",
            )
        return
    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing webhook signature")
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    provided = signature_header.split("=", 1)[1].strip()
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


def _summarise(event: str, payload: dict[str, Any]) -> tuple[str, str, str]:
    """Return (action, title, summary) for a webhook payload."""
    action = str(payload.get("action") or "")
    repo = str((payload.get("repository") or {}).get("full_name") or "")
    if event == "push":
        ref = str(payload.get("ref") or "").replace("refs/heads/", "")
        commits = payload.get("commits") or []
        head = payload.get("head_commit") or {}
        message = " ".join(str(head.get("message") or "").split())[:200]
        pusher = str((payload.get("pusher") or {}).get("name") or "")
        title = f"Push to {repo}@{ref}: {len(commits)} commit(s)"
        summary = f"{pusher} pushed {len(commits)} commit(s) to {ref}. Head: {message}"
        return "push", title, summary
    if event == "pull_request":
        pr = payload.get("pull_request") or {}
        number = payload.get("number") or pr.get("number")
        merged = bool(pr.get("merged"))
        state = "merged" if (action == "closed" and merged) else action
        title = f"PR #{number} {state}: {str(pr.get('title') or '')[:160]}"
        summary = (
            f"Pull request #{number} {state} by "
            f"{str((pr.get('user') or {}).get('login') or 'unknown')} "
            f"({pr.get('changed_files', '?')} files, +{pr.get('additions', '?')}/-{pr.get('deletions', '?')})"
        )
        return state, title, summary
    if event == "issues":
        issue = payload.get("issue") or {}
        title = f"Issue #{issue.get('number')} {action}: {str(issue.get('title') or '')[:160]}"
        return action, title, title
    if event == "issue_comment":
        issue = payload.get("issue") or {}
        comment = payload.get("comment") or {}
        body = " ".join(str(comment.get("body") or "").split())[:200]
        title = f"Comment on #{issue.get('number')} by {str((comment.get('user') or {}).get('login') or 'unknown')}"
        return action, title, f"{title}: {body}"
    if event in {"installation", "installation_repositories"}:
        repos = payload.get("repositories") or payload.get("repositories_added") or []
        names = ", ".join(str(item.get("full_name") or "") for item in repos[:10])
        title = f"GitHub App installation {action}"
        return action, title, f"{title}. Repositories: {names or 'n/a'}"
    if event == "workflow_run":
        run = payload.get("workflow_run") or {}
        title = (
            f"Workflow '{str(run.get('name') or '')[:80]}' "
            f"{str(run.get('conclusion') or run.get('status') or action)}"
        )
        return action, title, title
    if event == "check_suite":
        suite = payload.get("check_suite") or {}
        title = f"Check suite {str(suite.get('conclusion') or suite.get('status') or action)}"
        return action, title, title
    return action, f"GitHub event: {event}", f"Received GitHub event '{event}' ({action or 'no action'})"


@router.post("/webhook", summary="Receive GitHub App webhook deliveries")
async def receive_webhook(request: Request) -> dict:
    payload_bytes = await request.body()
    _verify_signature(payload_bytes, request.headers.get("X-Hub-Signature-256"))
    event = (request.headers.get("X-GitHub-Event") or "").strip().lower()
    if not event:
        raise HTTPException(status_code=400, detail="Missing X-GitHub-Event header")
    try:
        payload = json.loads(payload_bytes.decode() or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")

    if event == "ping":
        return {"ok": True, "pong": str(payload.get("zen") or "pong"), "handled": True}

    repository = str((payload.get("repository") or {}).get("full_name") or "")
    sender = str((payload.get("sender") or {}).get("login") or "")
    action, title, summary = _summarise(event, payload)

    record = {
        "id": f"ghe_{uuid.uuid4().hex[:20]}",
        "delivery_id": (request.headers.get("X-GitHub-Delivery") or "")[:80],
        "event": event,
        "action": action[:80],
        "repository": repository[:200],
        "sender": sender[:100],
        "summary": summary[:1000],
        "received_at": _now(),
    }
    with _connect() as db:
        db.execute(
            """INSERT INTO github_events
               (id, delivery_id, event, action, repository, sender, summary, received_at)
               VALUES (:id, :delivery_id, :event, :action, :repository, :sender, :summary, :received_at)""",
            record,
        )

    codex_memory.store_entry(
        scope=repository or codex_memory.GLOBAL_VOLUME,
        kind="event",
        title=title[:300],
        content=summary,
        tags=["github", event] + ([action] if action else []),
        importance=0.6 if event in {"push", "pull_request"} else 0.4,
        source=record["delivery_id"] or None,
    )
    return {"ok": True, "handled": event in HANDLED_EVENTS, "event_id": record["id"]}


@router.get("/events", summary="List recent GitHub App events")
async def list_events(
    request: Request,
    repository: str | None = None,
    event: str | None = None,
    limit: int = 30,
) -> dict:
    user = _authenticated_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to view GitHub events")
    conditions: list[str] = []
    parameters: list[Any] = []
    if repository:
        conditions.append("repository = ?")
        parameters.append(repository.strip()[:200])
    if event:
        conditions.append("event = ?")
        parameters.append(event.strip().lower()[:80])
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    parameters.append(max(1, min(limit, 200)))
    with _connect() as db:
        rows = db.execute(
            f"SELECT * FROM github_events {where} ORDER BY received_at DESC LIMIT ?",
            parameters,
        ).fetchall()
    return {"events": [dict(row) for row in rows], "count": len(rows)}


@router.get("/app", summary="GitHub App integration status")
async def app_status(request: Request) -> dict:
    user = _authenticated_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to view GitHub App status")
    with _connect() as db:
        row = db.execute(
            "SELECT COUNT(*) AS events, MAX(received_at) AS last_event_at FROM github_events"
        ).fetchone()
    return {
        "app_slug": os.getenv("GITHUB_APP_SLUG", "amosclaud-platform"),
        "webhook_path": "/api/v1/agent/github/webhook",
        "webhook_secret_configured": bool(_webhook_secret()),
        "events_recorded": row["events"],
        "last_event_at": row["last_event_at"],
        "handled_events": sorted(HANDLED_EVENTS),
    }
