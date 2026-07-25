"""Issue-driven Amosclaud commands for the signed GitHub App webhook.

A GitHub issue or issue comment can ask Amosclaud to fix, plan, review, or
explain work in a connected repository. The command is parsed from the signed
webhook delivery, authorized against a linked Amosclaud account, turned into a
normal Amosclaud task (``global_tasks``), executed through the existing cloud
task runner, and reported back to the originating issue.

Nothing here fabricates results: when no model runtime is connected the task
completes with a truthful blocker, and when no GitHub write credential is
configured the outbound comment is persisted as a pending relay instead of
being silently dropped.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

COMMANDS = ("fix", "plan", "review", "explain")
MENTIONS = ("/amosclaud-bot", "@amosclaud-bot", "/amosclaud", "@amosclaud")
LABEL_PREFIX = "amosclaud:"
LABEL_COMMANDS = ("fix", "plan", "review")
ISSUE_ACTIONS = {"opened", "edited", "labeled"}
COMMENT_ACTIONS = {"created", "edited"}
TRUSTED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
WRITE_ROLES = {"developer"}
TASK_MODES = {"fix": "fix", "plan": "ask", "review": "review", "explain": "ask"}
TASK_DELIVERY = {
    "fix": "pull_request",
    "plan": "report",
    "review": "report",
    "explain": "report",
}
MARKER = "<!-- amosclaud:issue-command -->"
DEFAULT_BOT_LOGIN = "amosclaud-platform[bot]"
BLOCKED_SUMMARY = (
    "Blocked: no Amosclaud model runtime is connected, so no code changes "
    "were made. Native repository actions (inspection, tests, branch and "
    "commit operations) remain available through the platform once a model "
    "station or first-party model endpoint is connected."
)
GITHUB_API = "https://api.github.com"


@dataclass(frozen=True)
class IssueCommand:
    """A recognised Amosclaud command carried by a GitHub issue delivery."""

    command: str
    instruction: str
    source: str
    event: str
    action: str
    repository: str
    issue_number: int
    issue_title: str
    issue_url: str
    comment_id: str
    sender: str
    association: str


@dataclass(frozen=True)
class Decision:
    """Result of the two-sided authorization check."""

    allowed: bool
    outcome: str
    detail: str
    account_id: int | None = None
    repository_full_name: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _inline_execution() -> bool:
    raw = os.getenv("AMOSCLAUD_GITHUB_COMMANDS_INLINE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _allowlist() -> set[str]:
    raw = os.getenv("AMOSCLAUD_GITHUB_COMMAND_ALLOWLIST", "")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _bot_logins() -> set[str]:
    configured = os.getenv("AMOSCLAUD_GITHUB_BOT_LOGIN", DEFAULT_BOT_LOGIN)
    logins = {item.strip().lower() for item in configured.split(",")}
    logins.add("amosclaud-bot")
    return {login for login in logins if login}


# --------------------------------------------------------------------------
# Command parsing
# --------------------------------------------------------------------------


def _command_from_body(body: str) -> tuple[str, str] | None:
    text = " ".join((body or "").split())
    if not text or MARKER in (body or ""):
        return None
    lowered = text.lower()
    for mention in MENTIONS:
        index = lowered.find(mention)
        if index < 0:
            continue
        remainder = text[index + len(mention):].strip(" :,-")
        word, _, rest = remainder.partition(" ")
        command = word.strip().lower().strip(":,.!")
        if command in COMMANDS:
            return command, rest.strip()
    return None


def _label_names(payload: dict[str, Any], issue: dict[str, Any]) -> list[str]:
    names: list[str] = []
    label = payload.get("label") or {}
    if isinstance(label, dict) and label.get("name"):
        names.append(str(label["name"]))
    for item in issue.get("labels") or []:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
        elif isinstance(item, str):
            names.append(item)
    return names


def _command_from_labels(names: list[str]) -> tuple[str, str] | None:
    for name in names:
        value = str(name or "").strip().lower()
        if not value.startswith(LABEL_PREFIX):
            continue
        command = value[len(LABEL_PREFIX):].strip()
        if command in LABEL_COMMANDS:
            return command, ""
    return None


def _issue_source(payload: dict[str, Any], issue: dict[str, Any]):
    """Return ((command, instruction), source) for an ``issues`` delivery."""
    found = _command_from_body(str(issue.get("body") or ""))
    if found:
        return found, "body"
    found = _command_from_body(str(issue.get("title") or ""))
    if found:
        return found, "title"
    found = _command_from_labels(_label_names(payload, issue))
    if found:
        return found, "label"
    return None, ""


def parse_issue_command(event: str, payload: dict[str, Any]) -> IssueCommand | None:
    """Parse an Amosclaud command out of an issue or issue-comment delivery."""
    action = str(payload.get("action") or "").strip().lower()
    issue = payload.get("issue") or {}
    repository = str((payload.get("repository") or {}).get("full_name") or "")
    comment_id = ""
    if event == "issue_comment":
        if action not in COMMENT_ACTIONS:
            return None
        comment = payload.get("comment") or {}
        found = _command_from_body(str(comment.get("body") or ""))
        source = "comment"
        comment_id = str(comment.get("id") or "")
        association = str(comment.get("author_association") or "NONE")
    elif event == "issues":
        if action not in ISSUE_ACTIONS:
            return None
        found, source = _issue_source(payload, issue)
        association = str(issue.get("author_association") or "NONE")
    else:
        return None
    if not found or not repository or not issue.get("number"):
        return None
    sender = str((payload.get("sender") or {}).get("login") or "")
    return IssueCommand(
        command=found[0],
        instruction=found[1][:8000],
        source=source,
        event=event,
        action=action,
        repository=repository[:200],
        issue_number=int(issue.get("number") or 0),
        issue_title=str(issue.get("title") or "")[:300],
        issue_url=str(issue.get("html_url") or "")[:400],
        comment_id=comment_id[:40],
        sender=sender[:100],
        association=association.upper()[:40],
    )


def _is_bot_sender(payload: dict[str, Any], command: IssueCommand) -> bool:
    sender = payload.get("sender") or {}
    if str(sender.get("type") or "").strip().lower() == "bot":
        return True
    login = command.sender.strip().lower()
    if not login or login.endswith("[bot]"):
        return True
    return login in _bot_logins()


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------


def _commands_db() -> sqlite3.Connection:
    from amoscloud_ai.api.routes.github_app import _events_db_path

    path = _events_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS github_issue_commands (
            id TEXT PRIMARY KEY,
            delivery_id TEXT NOT NULL DEFAULT '',
            dedupe_key TEXT NOT NULL UNIQUE,
            event TEXT NOT NULL,
            action TEXT NOT NULL DEFAULT '',
            repository TEXT NOT NULL,
            issue_number INTEGER NOT NULL,
            comment_id TEXT NOT NULL DEFAULT '',
            command TEXT NOT NULL,
            instruction TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            sender TEXT NOT NULL DEFAULT '',
            author_association TEXT NOT NULL DEFAULT '',
            authorized INTEGER NOT NULL DEFAULT 0,
            authorization_outcome TEXT NOT NULL DEFAULT 'pending',
            account_id INTEGER,
            task_id TEXT,
            task_status TEXT,
            relay_state TEXT NOT NULL DEFAULT 'none',
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_issue_commands_delivery
            ON github_issue_commands(delivery_id) WHERE delivery_id <> '';
        CREATE TABLE IF NOT EXISTS github_issue_relays (
            id TEXT PRIMARY KEY,
            command_id TEXT NOT NULL,
            dedupe_key TEXT NOT NULL UNIQUE,
            repository TEXT NOT NULL,
            issue_number INTEGER NOT NULL,
            kind TEXT NOT NULL,
            body TEXT NOT NULL,
            state TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            delivered_at TEXT
        );
        """
    )
    return db


def _dedupe_key(command: IssueCommand) -> str:
    return "|".join(
        [
            command.repository,
            str(command.issue_number),
            command.comment_id or "issue",
            command.command,
            command.source,
        ]
    )


def _claim(command: IssueCommand, delivery_id: str) -> tuple[str, dict | None]:
    """Reserve this command. Returns (record_id, existing_record_or_None)."""
    dedupe = _dedupe_key(command)
    delivery = (delivery_id or "")[:80]
    record_id = "ghic_" + uuid.uuid4().hex[:20]
    with _commands_db() as db:
        existing = db.execute(
            """SELECT * FROM github_issue_commands
               WHERE dedupe_key=? OR (delivery_id<>'' AND delivery_id=?)
               LIMIT 1""",
            (dedupe, delivery),
        ).fetchone()
        if existing:
            return str(existing["id"]), dict(existing)
        try:
            db.execute(
                """INSERT INTO github_issue_commands
                   (id,delivery_id,dedupe_key,event,action,repository,issue_number,
                    comment_id,command,instruction,source,sender,author_association,
                    authorized,authorization_outcome,relay_state,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,'pending','none',?,?)""",
                (
                    record_id,
                    delivery,
                    dedupe,
                    command.event,
                    command.action,
                    command.repository,
                    command.issue_number,
                    command.comment_id,
                    command.command,
                    command.instruction[:4000],
                    command.source,
                    command.sender,
                    command.association,
                    _now(),
                    _now(),
                ),
            )
            db.commit()
        except sqlite3.IntegrityError:
            row = db.execute(
                """SELECT * FROM github_issue_commands
                   WHERE dedupe_key=? OR (delivery_id<>'' AND delivery_id=?)
                   LIMIT 1""",
                (dedupe, delivery),
            ).fetchone()
            if row:
                return str(row["id"]), dict(row)
            raise
    return record_id, None


def _update_record(record_id: str, **fields: Any) -> None:
    allowed = {
        "authorized",
        "authorization_outcome",
        "account_id",
        "task_id",
        "task_status",
        "relay_state",
        "detail",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return
    assignments = ", ".join(f"{key}=?" for key in updates)
    with _commands_db() as db:
        db.execute(
            f"UPDATE github_issue_commands SET {assignments}, updated_at=? WHERE id=?",
            (*updates.values(), _now(), record_id),
        )
        db.commit()


def _record(record_id: str) -> dict | None:
    with _commands_db() as db:
        row = db.execute(
            "SELECT * FROM github_issue_commands WHERE id=?", (record_id,)
        ).fetchone()
    return dict(row) if row else None


# --------------------------------------------------------------------------
# Authorization
# --------------------------------------------------------------------------


def _table_exists(db: sqlite3.Connection, name: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return bool(row)


def _linked_account(db: sqlite3.Connection, login: str) -> int | None:
    if not login or not _table_exists(db, "github_connections"):
        return None
    row = db.execute(
        """SELECT user_id FROM github_connections
           WHERE lower(github_login)=lower(?) LIMIT 1""",
        (login,),
    ).fetchone()
    return int(row["user_id"]) if row else None


def _writable_repository(
    db: sqlite3.Connection, account_id: int, repository: str
) -> str | None:
    if not _table_exists(db, "repositories"):
        return None
    join = ""
    if _table_exists(db, "repository_collaborators"):
        join = (
            "LEFT JOIN repository_collaborators c "
            "ON c.repository_id=r.id AND c.user_id=? AND c.role IN ('developer') "
        )
        parameters: tuple = (account_id, repository, account_id)
    else:
        parameters = (repository, account_id)
    row = db.execute(
        f"""SELECT r.github_full_name AS full_name FROM repositories r
            {join}
            WHERE r.github_full_name=?
              AND (r.owner_id=?{' OR c.user_id IS NOT NULL' if join else ''})
            LIMIT 1""",
        parameters,
    ).fetchone()
    return str(row["full_name"]) if row and row["full_name"] else None


def authorize(command: IssueCommand) -> Decision:
    """Require a trusted GitHub association, a linked account, and write access."""
    from amoscloud_ai.api.routes.auth import _connect

    login = command.sender.strip().lower()
    if command.association not in TRUSTED_ASSOCIATIONS and login not in _allowlist():
        return Decision(
            False,
            "untrusted_association",
            "GitHub author association "
            f"'{command.association}' is not trusted for Amosclaud commands.",
        )
    with _connect() as db:
        account_id = _linked_account(db, command.sender)
        if account_id is None:
            return Decision(
                False,
                "no_linked_account",
                f"GitHub user '{command.sender}' is not linked to an "
                "Amosclaud account.",
            )
        full_name = _writable_repository(db, account_id, command.repository)
    if not full_name:
        return Decision(
            False,
            "no_repository_write_access",
            "The linked Amosclaud account does not hold write access to "
            f"'{command.repository}'.",
            account_id=account_id,
        )
    return Decision(
        True,
        "authorized",
        "Linked Amosclaud account holds write access to the target repository.",
        account_id=account_id,
        repository_full_name=full_name,
    )


# --------------------------------------------------------------------------
# Task creation and execution
# --------------------------------------------------------------------------


def _objective(command: IssueCommand) -> str:
    instruction = command.instruction.strip() or command.issue_title.strip()
    verb = {
        "fix": "Fix",
        "plan": "Plan the smallest safe fix for",
        "review": "Review",
        "explain": "Explain",
    }[command.command]
    text = (
        f"{verb} the problem reported in GitHub issue "
        f"#{command.issue_number} of {command.repository}: "
        f"{instruction or 'see the issue thread'}"
    )
    return text[:20_000]


def _task_metadata(command: IssueCommand, record_id: str) -> dict:
    return {
        "source": "github_issue_command",
        "issue_command_id": record_id,
        "bounded_execution": True,
        "github": {
            "repository": command.repository,
            "issue_number": command.issue_number,
            "issue_url": command.issue_url,
            "comment_id": command.comment_id,
            "command": command.command,
            "command_source": command.source,
            "sender": command.sender,
            "author_association": command.association,
        },
    }


def _create_task(command: IssueCommand, decision: Decision, record_id: str) -> dict:
    """Create a normal Amosclaud task bound to the resolved repository."""
    from amoscloud_ai.agent_tokens import debit_tokens
    from amoscloud_ai.api.routes.auth import _connect
    from amoscloud_ai.api.routes.operation_buckets import ensure_user_bucket
    from amoscloud_ai.api.routes.task_router import (
        TaskCreate,
        _ensure_schema,
        _event,
        _json,
        _task_cost,
    )

    mode = TASK_MODES[command.command]
    body = TaskCreate(
        objective=_objective(command),
        repository=decision.repository_full_name,
        mode=mode,
        delivery=TASK_DELIVERY[command.command],
        execution_target="github",
        require_approval=False,
        metadata=_task_metadata(command, record_id),
    )
    task_id = "task_" + uuid.uuid4().hex
    cost = _task_cost(body)
    account_id = int(decision.account_id or 0)
    with _connect() as db:
        _ensure_schema(db)
        if not debit_tokens(db, account_id, cost, reference=task_id):
            return {"ok": False, "reason": "agent_tokens_required"}
        bucket = ensure_user_bucket(db, account_id, commit=False)
        db.execute(
            """INSERT INTO global_tasks
               (id,user_id,bucket_id,repository,objective,mode,delivery,status,
                execution_target,runner_id,require_approval,reserved_credits,
                metadata_json,created_at)
               VALUES (?,?,?,?,?,?,?,'queued','github',NULL,0,?,?,?)""",
            (
                task_id,
                account_id,
                bucket["id"],
                body.repository,
                body.objective,
                body.mode,
                body.delivery,
                cost,
                _json(body.metadata),
                _now(),
            ),
        )
        _event(
            db,
            task_id,
            "task.created",
            "Task accepted from a GitHub issue command.",
            {
                "credits_reserved": cost,
                "bucket_id": bucket["id"],
                "issue_command_id": record_id,
                "github_issue": f"{command.repository}#{command.issue_number}",
            },
        )
        db.commit()
    return {"ok": True, "task_id": task_id, "mode": mode, "cost": cost}


def _runtime_ready() -> bool:
    from amoscloud_ai import provider

    try:
        return bool(provider.is_configured())
    except Exception:
        return False


def _finish_blocked(task_id: str) -> None:
    from amoscloud_ai.cloud_task_runner import _finish, _verification_id

    evidence = [
        "Model runtime probe: no first-party model station or endpoint is "
        "connected (provider.is_configured() returned False).",
        "No branch, commit, or file change was produced for this task.",
        "Native repository actions remain available inside the platform.",
    ]
    _finish(
        task_id,
        "completed",
        BLOCKED_SUMMARY,
        evidence=evidence,
        verification_id=_verification_id(task_id, "no-runtime", evidence),
    )


def _branch_name(task_id: str) -> str:
    return f"amosclaud/task-{task_id.removeprefix('task_')[:12]}"


def _task_outcome(task_id: str) -> dict:
    from amoscloud_ai.api.routes.auth import _connect
    from amoscloud_ai.api.routes.task_router import _ensure_schema, _loads

    with _connect() as db:
        _ensure_schema(db)
        row = db.execute(
            "SELECT * FROM global_tasks WHERE id=?", (task_id,)
        ).fetchone()
        events = db.execute(
            """SELECT event_type,details_json FROM global_task_events
               WHERE task_id=? ORDER BY id DESC LIMIT 5""",
            (task_id,),
        ).fetchall()
    if not row:
        return {"status": "unknown", "summary": "Task record is unavailable."}
    evidence: list[str] = []
    for event in events:
        details = _loads(event["details_json"], {})
        for item in details.get("evidence") or []:
            evidence.append(str(item))
        if evidence:
            break
    artifacts = _loads(row["artifacts_json"], [])
    commit_sha = ""
    for artifact in artifacts:
        if isinstance(artifact, dict) and artifact.get("commit_sha"):
            commit_sha = str(artifact["commit_sha"])
    return {
        "status": str(row["status"]),
        "summary": str(row["summary"] or ""),
        "branch": _branch_name(task_id),
        "commit_sha": commit_sha,
        "pull_request_url": row["pull_request_url"] or "",
        "verification_id": row["verification_id"] or "",
        "evidence": evidence[:8],
    }


def _execute_task(task_id: str) -> None:
    """Run the task through the existing in-platform cloud task runner."""
    from amoscloud_ai.cloud_task_runner import execute_cloud_task

    execute_cloud_task(task_id)


def _run_and_report(record_id: str, task_id: str) -> None:
    detail = ""
    try:
        _execute_task(task_id)
    except Exception as exc:  # keep the relay honest about runtime failures
        detail = f"Execution stopped: {type(exc).__name__}"
    outcome = _task_outcome(task_id)
    relay = relay_comment(record_id, "completion", _completion_comment(outcome))
    _update_record(
        record_id,
        task_status=outcome["status"],
        relay_state=relay["state"],
        detail=(detail or relay.get("detail") or "")[:2000],
    )


def _start_execution(record_id: str, task_id: str) -> None:
    if _inline_execution():
        _run_and_report(record_id, task_id)
        return
    threading.Thread(
        target=_run_and_report,
        args=(record_id, task_id),
        name=f"amosclaud-issue-{task_id[-8:]}",
        daemon=True,
    ).start()


# --------------------------------------------------------------------------
# Outbound relay to the GitHub issue
# --------------------------------------------------------------------------


def _relay_token(account_id: int | None) -> str:
    for name in ("AMOSCLAUD_GITHUB_COMMENT_TOKEN", "GITHUB_TOKEN"):
        token = os.getenv(name, "").strip()
        if token:
            return token
    if not account_id:
        return ""
    try:
        from amoscloud_ai.api.routes.auth import _connect
        from amoscloud_ai.api.routes.github_repositories import _decrypt_token

        with _connect() as db:
            if not _table_exists(db, "github_connections"):
                return ""
            row = db.execute(
                """SELECT access_token_ciphertext FROM github_connections
                   WHERE user_id=?""",
                (int(account_id),),
            ).fetchone()
        if not row:
            return ""
        return _decrypt_token(str(row["access_token_ciphertext"]))
    except Exception:
        return ""


def _post_comment(
    repository: str, issue_number: int, body: str, token: str
) -> tuple[bool, str]:
    url = f"{GITHUB_API}/repos/{repository}/issues/{issue_number}/comments"
    try:
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"body": body},
            timeout=20,
        )
    except Exception as exc:
        return False, f"GitHub comment transport error: {type(exc).__name__}"
    if response.status_code >= 300:
        return False, f"GitHub responded {response.status_code} to the comment"
    try:
        return True, str((response.json() or {}).get("html_url") or "")
    except (json.JSONDecodeError, ValueError):
        return True, ""


def relay_comment(record_id: str, kind: str, body: str) -> dict:
    """Post one de-duplicated comment, or persist a pending relay record."""
    record = _record(record_id)
    if not record:
        return {"state": "skipped", "detail": "Command record is unavailable."}
    dedupe = f"{record_id}:{kind}"
    relay_id = "ghrl_" + uuid.uuid4().hex[:20]
    with _commands_db() as db:
        existing = db.execute(
            "SELECT * FROM github_issue_relays WHERE dedupe_key=?", (dedupe,)
        ).fetchone()
        if existing:
            return {
                "state": str(existing["state"]),
                "kind": kind,
                "duplicate": True,
                "detail": str(existing["detail"] or ""),
            }
        try:
            db.execute(
                """INSERT INTO github_issue_relays
                   (id,command_id,dedupe_key,repository,issue_number,kind,body,
                    state,detail,created_at)
                   VALUES (?,?,?,?,?,?,?,'pending','',?)""",
                (
                    relay_id,
                    record_id,
                    dedupe,
                    record["repository"],
                    int(record["issue_number"]),
                    kind,
                    body[:60_000],
                    _now(),
                ),
            )
            db.commit()
        except sqlite3.IntegrityError:
            return {"state": "pending", "kind": kind, "duplicate": True, "detail": ""}
    token = _relay_token(record.get("account_id"))
    if not token:
        detail = (
            "No GitHub write credential is configured; the comment is stored "
            "as a pending outbound relay."
        )
        _set_relay_state(relay_id, "pending", detail)
        return {"state": "pending", "kind": kind, "detail": detail}
    delivered, detail = _post_comment(
        str(record["repository"]), int(record["issue_number"]), body, token
    )
    _set_relay_state(relay_id, "delivered" if delivered else "pending", detail)
    return {
        "state": "delivered" if delivered else "pending",
        "kind": kind,
        "detail": detail,
    }


def _set_relay_state(relay_id: str, state: str, detail: str) -> None:
    with _commands_db() as db:
        db.execute(
            """UPDATE github_issue_relays
               SET state=?,detail=?,delivered_at=? WHERE id=?""",
            (state, detail[:1000], _now() if state == "delivered" else None, relay_id),
        )
        db.commit()


def pending_relays(limit: int = 50) -> list[dict]:
    with _commands_db() as db:
        rows = db.execute(
            """SELECT id,command_id,repository,issue_number,kind,state,detail,created_at
               FROM github_issue_relays WHERE state='pending'
               ORDER BY created_at DESC LIMIT ?""",
            (max(1, min(limit, 200)),),
        ).fetchall()
    return [dict(row) for row in rows]


def _acknowledgement_comment(command: IssueCommand, task_id: str, mode: str) -> str:
    plan = {
        "fix": (
            "create a working branch, apply the smallest bounded change, run the "
            "repository tests, and record verification evidence"
        ),
        "plan": "inspect the repository and return a plan without changing files",
        "review": "review the repository state and report findings",
        "explain": "explain the reported behaviour without changing files",
    }[command.command]
    return "\n".join(
        [
            MARKER,
            "### Amosclaud accepted this request",
            f"- **Task:** `{task_id}`",
            f"- **Command:** `{command.command}` (from {command.source})",
            f"- **Repository:** `{command.repository}`",
            f"- **Mode:** `{mode}`",
            f"- **Plan:** Amosclaud will {plan}.",
            "",
            "The outcome, including test and verification evidence, will be "
            "posted here when the task finishes.",
        ]
    )


def _completion_comment(outcome: dict) -> str:
    lines = [
        MARKER,
        f"### Amosclaud task {outcome.get('status', 'unknown')}",
        f"- **Status:** `{outcome.get('status', 'unknown')}`",
        f"- **Branch:** `{outcome.get('branch') or 'none'}`",
        f"- **Commit:** `{outcome.get('commit_sha') or 'none'}`",
    ]
    if outcome.get("pull_request_url"):
        lines.append(f"- **Pull request:** {outcome['pull_request_url']}")
    if outcome.get("verification_id"):
        lines.append(f"- **Verification:** `{outcome['verification_id']}`")
    summary = str(outcome.get("summary") or "").strip()
    if summary:
        lines.extend(["", "**Summary**", summary[:1500]])
    evidence = [str(item)[:300] for item in outcome.get("evidence") or []]
    if evidence:
        lines.append("")
        lines.append("**Evidence**")
        lines.extend(f"- {item}" for item in evidence[:8])
    return "\n".join(lines)[:60_000]


def _refusal_comment(command: IssueCommand, decision: Decision) -> str:
    return "\n".join(
        [
            MARKER,
            "### Amosclaud did not run this command",
            f"- **Command:** `{command.command}`",
            f"- **Requested by:** `{command.sender}`",
            f"- **Reason:** `{decision.outcome}`",
            "",
            decision.detail,
            "",
            "The event was recorded, no task was created, and no repository "
            "change was attempted. Link a GitHub account with Amosclaud write "
            "access to the target repository and try again.",
        ]
    )


# --------------------------------------------------------------------------
# Entry point used by the signed webhook route
# --------------------------------------------------------------------------


def handle_issue_event(
    *, event: str, payload: dict[str, Any], delivery_id: str = ""
) -> dict | None:
    """Handle one issue delivery. Returns None for non-command activity."""
    try:
        return _handle_issue_event(event, payload, delivery_id)
    except Exception as exc:
        return {"status": "error", "detail": f"{type(exc).__name__}"}


def _refuse(record_id: str, command: IssueCommand, decision: Decision) -> dict:
    _update_record(
        record_id,
        authorized=0,
        authorization_outcome=decision.outcome,
        account_id=decision.account_id,
        detail=decision.detail[:2000],
    )
    relay = relay_comment(record_id, "refusal", _refusal_comment(command, decision))
    _update_record(record_id, relay_state=relay["state"])
    return {
        "status": "refused",
        "command": command.command,
        "reason": decision.outcome,
        "command_id": record_id,
        "relay_state": relay["state"],
    }


def _handle_issue_event(
    event: str, payload: dict[str, Any], delivery_id: str
) -> dict | None:
    command = parse_issue_command(event, payload)
    if not command:
        return None
    if _is_bot_sender(payload, command):
        return {"status": "ignored", "reason": "bot_sender", "command": command.command}
    record_id, existing = _claim(command, delivery_id)
    if existing:
        return {
            "status": "already_handled",
            "command": command.command,
            "command_id": record_id,
            "task_id": existing.get("task_id"),
            "authorization": existing.get("authorization_outcome"),
        }
    decision = authorize(command)
    if not decision.allowed:
        return _refuse(record_id, command, decision)
    created = _create_task(command, decision, record_id)
    if not created.get("ok"):
        return _refuse(
            record_id,
            command,
            Decision(
                False,
                str(created.get("reason") or "task_not_created"),
                "The linked Amosclaud account does not hold enough agent "
                "tokens to run this task.",
                account_id=decision.account_id,
            ),
        )
    task_id = str(created["task_id"])
    _update_record(
        record_id,
        authorized=1,
        authorization_outcome="authorized",
        account_id=decision.account_id,
        task_id=task_id,
        task_status="queued",
        detail=decision.detail[:2000],
    )
    relay = relay_comment(
        record_id,
        "acknowledgement",
        _acknowledgement_comment(command, task_id, str(created["mode"])),
    )
    _update_record(record_id, relay_state=relay["state"])
    if not _runtime_ready():
        _finish_blocked(task_id)
        outcome = _task_outcome(task_id)
        blocked = relay_comment(record_id, "completion", _completion_comment(outcome))
        _update_record(
            record_id, task_status=outcome["status"], relay_state=blocked["state"]
        )
        return {
            "status": "blocked",
            "command": command.command,
            "command_id": record_id,
            "task_id": task_id,
            "task_status": outcome["status"],
            "reason": "no_model_runtime",
            "relay_state": blocked["state"],
        }
    _start_execution(record_id, task_id)
    return {
        "status": "accepted",
        "command": command.command,
        "command_id": record_id,
        "task_id": task_id,
        "mode": created["mode"],
        "repository": decision.repository_full_name,
        "relay_state": relay["state"],
    }


def recent_issue_commands(
    limit: int = 30, repository: str | None = None
) -> list[dict]:
    """Issue-driven task bindings for platform visibility."""
    conditions: list[str] = []
    parameters: list[Any] = []
    if repository:
        conditions.append("repository=?")
        parameters.append(repository.strip()[:200])
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    parameters.append(max(1, min(limit, 200)))
    with _commands_db() as db:
        rows = db.execute(
            f"""SELECT id,delivery_id,event,action,repository,issue_number,comment_id,
                       command,instruction,source,sender,author_association,authorized,
                       authorization_outcome,task_id,task_status,relay_state,detail,
                       created_at,updated_at
                FROM github_issue_commands {where}
                ORDER BY created_at DESC LIMIT ?""",
            parameters,
        ).fetchall()
    items = [dict(row) for row in rows]
    statuses = _task_statuses(
        [str(item["task_id"]) for item in items if item["task_id"]]
    )
    for item in items:
        item["authorized"] = bool(item["authorized"])
        item["issue"] = f"{item['repository']}#{item['issue_number']}"
        live = statuses.get(str(item.get("task_id") or ""))
        if live:
            item["task_status"] = live["status"]
            item["pull_request_url"] = live["pull_request_url"]
            item["verification_id"] = live["verification_id"]
    return items


def _task_statuses(task_ids: list[str]) -> dict[str, dict]:
    if not task_ids:
        return {}
    from amoscloud_ai.api.routes.auth import _connect
    from amoscloud_ai.api.routes.task_router import _ensure_schema

    placeholders = ",".join("?" for _ in task_ids)
    with _connect() as db:
        _ensure_schema(db)
        rows = db.execute(
            f"""SELECT id,status,pull_request_url,verification_id
                FROM global_tasks WHERE id IN ({placeholders})""",
            task_ids,
        ).fetchall()
    return {
        str(row["id"]): {
            "status": str(row["status"]),
            "pull_request_url": row["pull_request_url"] or "",
            "verification_id": row["verification_id"] or "",
        }
        for row in rows
    }
