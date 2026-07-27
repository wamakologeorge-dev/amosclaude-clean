"""Inbound GitHub App integration for the Amosclaud platform.

Receives webhook deliveries from the "Amosclaud Platform" GitHub App at
``/api/v1/agent/github/webhook``, verifies their signatures, records every
event into the repository's codex memory volume, and exposes a queryable event
feed so GitHub activity becomes a first-class tool inside the platform.
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

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from amoscloud_ai import codex_memory, github_issue_commands
from amoscloud_ai.api.routes.agent import _authenticated_user
from amoscloud_ai.github_repository_sync import synchronize_github_push

router = APIRouter(prefix="/agent/github", tags=["github-app"])

HANDLED_EVENTS = {
    "ping",
    "push",
    "pull_request",
    "issues",
    "issue_comment",
    "installation",
    "installation_repositories",
    "repository",
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
    return os.getenv("AMOSCLAUD_ENV", "development").lower() in {
        "production",
        "prod",
    }


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
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature_header.strip()):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


def _github_to_platform_policy() -> tuple[bool, str]:
    try:
        configuration = load_cloud_configuration()
    except (OSError, ValueError, json.JSONDecodeError):
        return False, "server-managed cloud configuration is unavailable"
    sync = configuration.organization_settings.get("repository_sync") or {}
    direction = str(sync.get("direction") or "").strip().lower()
    mode = str(sync.get("github_to_platform") or "").strip().lower()
    direction_allows = direction in {
        "bidirectional",
        "github-to-platform",
        "github_to_platform",
        "inbound",
    }
    mode_allows = mode not in {"", "disabled", "none", "off", "false"}
    if not direction_allows:
        return False, f"repository_sync.direction={direction or 'unset'}"
    if not mode_allows:
        return False, f"repository_sync.github_to_platform={mode or 'unset'}"
    return True, mode


def _repository_identity(payload: dict[str, Any]) -> tuple[int | None, str]:
    repository = payload.get("repository") or {}
    raw_id = repository.get("id")
    try:
        repository_id = int(raw_id) if raw_id is not None else None
    except (TypeError, ValueError):
        repository_id = None
    return repository_id, str(repository.get("full_name") or "").strip()


def _previous_repository_full_name(payload: dict[str, Any]) -> str | None:
    repository = payload.get("repository") or {}
    owner = str((repository.get("owner") or {}).get("login") or "").strip()
    changes = payload.get("changes") or {}
    previous_name = str(
        ((changes.get("repository") or {}).get("name") or {}).get("from") or ""
    ).strip()
    if owner and previous_name:
        return f"{owner}/{previous_name}"
    previous_owner = str(
        ((changes.get("owner") or {}).get("from") or {}).get("login") or ""
    ).strip()
    current_name = str(repository.get("name") or "").strip()
    if previous_owner and current_name:
        return f"{previous_owner}/{current_name}"
    return None


def _refresh_repository_mapping(
    payload: dict[str, Any],
    event: str,
    action: str,
) -> None:
    github_repository_id, full_name = _repository_identity(payload)
    if not github_repository_id or not full_name:
        return
    repository = payload.get("repository") or {}
    html_url = str(repository.get("html_url") or "")
    default_branch = str(repository.get("default_branch") or "")
    previous_full_name = (
        _previous_repository_full_name(payload)
        if event == "repository" and action in {"renamed", "transferred"}
        else None
    )
    with _repository_db() as db:
        ensure_github_repository_schema(db)
        if previous_full_name:
            db.execute(
                """UPDATE repositories
                   SET github_repository_id=?, github_full_name=?, github_html_url=?,
                       github_default_branch=COALESCE(NULLIF(?, ''), github_default_branch)
                   WHERE github_repository_id=?
                      OR github_full_name=? COLLATE NOCASE""",
                (
                    github_repository_id,
                    full_name,
                    html_url,
                    default_branch,
                    github_repository_id,
                    previous_full_name,
                ),
            )
        else:
            db.execute(
                """UPDATE repositories
                   SET github_repository_id=?, github_full_name=?, github_html_url=?,
                       github_default_branch=COALESCE(NULLIF(?, ''), github_default_branch)
                   WHERE github_repository_id=?
                      OR (github_repository_id IS NULL
                          AND github_full_name=? COLLATE NOCASE)""",
                (
                    github_repository_id,
                    full_name,
                    html_url,
                    default_branch,
                    github_repository_id,
                    full_name,
                ),
            )
        db.commit()


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
    if event == "repository":
        title = f"Repository {action}: {repo}"
        return action, title, title
    if event == "pull_request":
        pr = payload.get("pull_request") or {}
        number = payload.get("number") or pr.get("number")
        merged = bool(pr.get("merged"))
        state = "merged" if (action == "closed" and merged) else action
        title = f"PR #{number} {state}: {str(pr.get('title') or '')[:160]}"
        summary = (
            f"Pull request #{number} {state} by "
            f"{str((pr.get('user') or {}).get('login') or 'unknown')} "
            f"({pr.get('changed_files', '?')} files, "
            f"+{pr.get('additions', '?')}/-{pr.get('deletions', '?')})"
        )
        return state, title, summary
    if event == "issues":
        issue = payload.get("issue") or {}
        title = (
            f"Issue #{issue.get('number')} {action}: "
            f"{str(issue.get('title') or '')[:160]}"
        )
        return action, title, title
    if event == "issue_comment":
        issue = payload.get("issue") or {}
        comment = payload.get("comment") or {}
        body = " ".join(str(comment.get("body") or "").split())[:200]
        title = (
            f"Comment on #{issue.get('number')} by "
            f"{str((comment.get('user') or {}).get('login') or 'unknown')}"
        )
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
        title = (
            f"Check suite {str(suite.get('conclusion') or suite.get('status') or action)}"
        )
        return action, title, title
    return (
        action,
        f"GitHub event: {event}",
        f"Received GitHub event '{event}' ({action or 'no action'})",
    )


@router.post("/webhook", summary="Receive GitHub App webhook deliveries")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    payload_bytes = await request.body()
    _verify_signature(
        payload_bytes,
        request.headers.get("X-Hub-Signature-256"),
    )
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
        return {
            "ok": True,
            "pong": str(payload.get("zen") or "pong"),
            "handled": True,
        }

    repository_id, repository = _repository_identity(payload)
    sender = str((payload.get("sender") or {}).get("login") or "")
    action, title, summary = _summarise(event, payload)
    _refresh_repository_mapping(payload, event, action)

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
    response = {
        "ok": True,
        "handled": event in HANDLED_EVENTS,
        "event_id": record["id"],
    }
    if event == "push" and repository:
        background_tasks.add_task(
            synchronize_github_push,
            repository,
            str(payload.get("ref") or ""),
            str(payload.get("after") or "") or None,
        )
        response["sync_queued"] = True
    if event in {"issues", "issue_comment"}:
        command = github_issue_commands.handle_issue_event(
            event=event,
            payload=payload,
            delivery_id=record["delivery_id"],
        )
        if command:
            response["issue_command"] = command
    return response


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


@router.get("/issue-commands", summary="List issue-driven Amosclaud tasks")
async def list_issue_commands(
    request: Request,
    repository: str | None = None,
    limit: int = 30,
) -> dict:
    user = _authenticated_user(request)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Sign in to view issue-driven Amosclaud tasks",
        )
    items = github_issue_commands.recent_issue_commands(
        limit=limit,
        repository=repository,
    )
    return {
        "issue_commands": items,
        "count": len(items),
        "pending_relays": github_issue_commands.pending_relays(),
        "commands": sorted(github_issue_commands.COMMANDS),
        "labels": [
            f"{github_issue_commands.LABEL_PREFIX}{name}"
            for name in github_issue_commands.LABEL_COMMANDS
        ],
    }


@router.get("/app", summary="GitHub App integration status")
async def app_status(request: Request) -> dict:
    user = _authenticated_user(request)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Sign in to view GitHub App status",
        )
    with _connect() as db:
        row = db.execute(
            "SELECT COUNT(*) AS events, MAX(received_at) AS last_event_at FROM github_events"
        ).fetchone()
    enabled, policy = _github_to_platform_policy()
    return {
        "app_slug": os.getenv("GITHUB_APP_SLUG", "amosclaud-platform"),
        "webhook_path": "/api/v1/agent/github/webhook",
        "webhook_secret_configured": bool(_webhook_secret()),
        "events_recorded": row["events"],
        "last_event_at": row["last_event_at"],
        "handled_events": sorted(HANDLED_EVENTS),
        "push_sync": {
            "enabled": True,
            "mode": "fast-forward-only",
            "conflict_policy": "never overwrite dirty, ahead, or diverged work",
        },
        "issue_commands": {
            "commands": sorted(github_issue_commands.COMMANDS),
            "mentions": list(github_issue_commands.MENTIONS),
            "labels": [
                f"{github_issue_commands.LABEL_PREFIX}{name}"
                for name in github_issue_commands.LABEL_COMMANDS
            ],
        },
    }
