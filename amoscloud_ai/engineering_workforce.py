"""Autonomous engineering workforce, hybrid execution, assets, and guardrails.

This module deliberately builds on Amosclaud's existing durable Global Task Router,
private runners, connected GitHub repositories, isolated verification, and operation
buckets. It does not create a second agent brain. A delegation is one governed work
order for the single Amosclaud Autonomous core.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from urllib.parse import urlparse

from amoscloud_ai.api.routes import task_router
from amoscloud_ai.autonomous_builder import (
    DEFAULT_ALLOWED_PATHS,
    DEFAULT_PROTECTED_PATHS,
    normalize_prefixes,
)

ONLINE_WINDOW = timedelta(seconds=90)
ASSET_STALE_WINDOW = timedelta(minutes=5)

DELEGATION_KINDS = {"epic", "feature", "bug", "refactor", "maintenance", "requirement"}
DELEGATION_STATUSES = {
    "planning",
    "awaiting_approval",
    "queued",
    "running",
    "completed",
    "failed",
    "blocked",
    "cancelled",
}
ASSET_TYPES = {"service", "micro_saas", "data_pipeline", "agent", "library", "website"}
ASSET_ENVIRONMENTS = {"development", "staging", "production"}

_DEFAULT_PROTECTED_BRANCHES = ("main", "master", "production", "release")
_DEFAULT_BRANCH_PREFIX = "amosclaud/workforce"
_SECRET_RE = re.compile(
    r"(?i)(?:authorization\s*:\s*bearer\s+\S+|"
    r"(?:token|secret|password|api[_-]?key)\s*[:=]\s*\S+|"
    r"gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})"
)


class WorkforcePolicyError(RuntimeError):
    """Raised when a requested workforce action crosses an immutable guardrail."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, sort_keys=True)


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def redact(value: str, limit: int = 8_000) -> str:
    """Remove likely credentials before user-provided telemetry is persisted."""

    text = str(value or "").replace("\x00", "")
    text = _SECRET_RE.sub("[redacted]", text)
    return text[-limit:]


def ensure_workforce_schema(db: sqlite3.Connection, *, commit: bool = True) -> None:
    """Create the workforce, asset, and guardrail ledgers idempotently."""

    task_router._ensure_schema(db)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS workforce_guardrails (
            user_id INTEGER PRIMARY KEY,
            allowed_paths_json TEXT NOT NULL,
            protected_paths_json TEXT NOT NULL,
            protected_branches_json TEXT NOT NULL,
            branch_prefix TEXT NOT NULL,
            max_repair_attempts INTEGER NOT NULL DEFAULT 3
                CHECK(max_repair_attempts BETWEEN 1 AND 3),
            require_tests INTEGER NOT NULL DEFAULT 1 CHECK(require_tests = 1),
            require_isolated_execution INTEGER NOT NULL DEFAULT 1
                CHECK(require_isolated_execution = 1),
            require_draft_pull_request INTEGER NOT NULL DEFAULT 1
                CHECK(require_draft_pull_request = 1),
            require_human_merge INTEGER NOT NULL DEFAULT 1
                CHECK(require_human_merge = 1),
            require_rollback_checkpoint INTEGER NOT NULL DEFAULT 1
                CHECK(require_rollback_checkpoint = 1),
            secret_masking INTEGER NOT NULL DEFAULT 1 CHECK(secret_masking = 1),
            allow_force_push INTEGER NOT NULL DEFAULT 0 CHECK(allow_force_push = 0),
            allow_direct_protected_branch_write INTEGER NOT NULL DEFAULT 0
                CHECK(allow_direct_protected_branch_write = 0),
            allow_auto_merge INTEGER NOT NULL DEFAULT 0 CHECK(allow_auto_merge = 0),
            production_deploy_requires_approval INTEGER NOT NULL DEFAULT 1
                CHECK(production_deploy_requires_approval = 1),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS workforce_delegations (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            repository TEXT NOT NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            requirement TEXT NOT NULL,
            source_reference TEXT,
            acceptance_criteria_json TEXT NOT NULL,
            execution_preference TEXT NOT NULL,
            execution_target TEXT,
            runner_id TEXT,
            status TEXT NOT NULL,
            task_id TEXT,
            guardrails_json TEXT NOT NULL,
            plan_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(task_id) REFERENCES global_tasks(id),
            FOREIGN KEY(runner_id) REFERENCES task_runners(id)
        );
        CREATE INDEX IF NOT EXISTS idx_workforce_delegations_owner_created
            ON workforce_delegations(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_workforce_delegations_task
            ON workforce_delegations(task_id);

        CREATE TABLE IF NOT EXISTS workforce_delegation_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            delegation_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(delegation_id) REFERENCES workforce_delegations(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_workforce_delegation_events_delegation
            ON workforce_delegation_events(delegation_id, id);

        CREATE TABLE IF NOT EXISTS software_assets (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            repository TEXT,
            asset_type TEXT NOT NULL,
            environment TEXT NOT NULL,
            target_url TEXT,
            telemetry_token_hash TEXT NOT NULL UNIQUE,
            telemetry_token_prefix TEXT NOT NULL,
            lifecycle_status TEXT NOT NULL DEFAULT 'active',
            license_reference TEXT,
            transfer_notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_software_assets_owner_updated
            ON software_assets(user_id, updated_at DESC);

        CREATE TABLE IF NOT EXISTS software_asset_telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            online INTEGER NOT NULL CHECK(online IN (0,1)),
            status_code INTEGER,
            latency_ms REAL,
            cpu_percent REAL,
            memory_mb REAL,
            error_count INTEGER NOT NULL DEFAULT 0,
            request_count INTEGER NOT NULL DEFAULT 0,
            active_users INTEGER,
            revenue_cents INTEGER,
            patch_success_count INTEGER,
            patch_failure_count INTEGER,
            metadata_json TEXT NOT NULL,
            FOREIGN KEY(asset_id) REFERENCES software_assets(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_software_asset_telemetry_asset_time
            ON software_asset_telemetry(asset_id, observed_at DESC);

        CREATE TABLE IF NOT EXISTS software_asset_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(asset_id) REFERENCES software_assets(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_software_asset_events_asset_time
            ON software_asset_events(asset_id, created_at DESC);
        """
    )
    if commit:
        db.commit()


def ensure_guardrails(
    db: sqlite3.Connection,
    user_id: int,
    *,
    commit: bool = True,
) -> sqlite3.Row:
    ensure_workforce_schema(db, commit=False)
    now = _now()
    db.execute(
        """INSERT OR IGNORE INTO workforce_guardrails(
               user_id,allowed_paths_json,protected_paths_json,protected_branches_json,
               branch_prefix,max_repair_attempts,created_at,updated_at
           ) VALUES (?,?,?,?,?,?,?,?)""",
        (
            user_id,
            _json(list(DEFAULT_ALLOWED_PATHS)),
            _json(list(DEFAULT_PROTECTED_PATHS)),
            _json(list(_DEFAULT_PROTECTED_BRANCHES)),
            _DEFAULT_BRANCH_PREFIX,
            3,
            now,
            now,
        ),
    )
    row = db.execute(
        "SELECT * FROM workforce_guardrails WHERE user_id=?",
        (user_id,),
    ).fetchone()
    if not row:
        raise RuntimeError("Unable to provision workforce guardrails")
    if commit:
        db.commit()
    return row


def guardrail_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["allowed_paths"] = _loads(item.pop("allowed_paths_json"), [])
    item["protected_paths"] = _loads(item.pop("protected_paths_json"), [])
    item["protected_branches"] = _loads(item.pop("protected_branches_json"), [])
    for name in (
        "require_tests",
        "require_isolated_execution",
        "require_draft_pull_request",
        "require_human_merge",
        "require_rollback_checkpoint",
        "secret_masking",
        "allow_force_push",
        "allow_direct_protected_branch_write",
        "allow_auto_merge",
        "production_deploy_requires_approval",
    ):
        item[name] = bool(item[name])
    return item


def guardrail_snapshot(row: sqlite3.Row) -> dict[str, Any]:
    item = guardrail_dict(row)
    return {
        "version": 1,
        "allowed_paths": item["allowed_paths"],
        "protected_paths": item["protected_paths"],
        "protected_branches": item["protected_branches"],
        "branch_prefix": item["branch_prefix"],
        "max_repair_attempts": item["max_repair_attempts"],
        "require_tests": True,
        "require_isolated_execution": True,
        "require_draft_pull_request": True,
        "require_human_merge": True,
        "require_rollback_checkpoint": True,
        "secret_masking": True,
        "force_push": False,
        "direct_protected_branch_write": False,
        "auto_merge": False,
        "production_deploy_requires_approval": True,
    }


def update_guardrails(
    db: sqlite3.Connection,
    user_id: int,
    *,
    allowed_paths: list[str],
    protected_paths: list[str],
    protected_branches: list[str],
    branch_prefix: str,
    max_repair_attempts: int,
) -> sqlite3.Row:
    ensure_guardrails(db, user_id, commit=False)
    allowed = normalize_prefixes(allowed_paths)
    protected = normalize_prefixes(protected_paths)
    branches = sorted({item.strip() for item in protected_branches if item.strip()})
    prefix = branch_prefix.strip().strip("/")
    if not allowed:
        raise WorkforcePolicyError("At least one autonomous write path is required")
    if not branches:
        raise WorkforcePolicyError("At least one protected branch is required")
    if any(part in {"", ".", ".."} for part in prefix.split("/")):
        raise WorkforcePolicyError("Use a safe branch prefix")
    if not re.fullmatch(r"[A-Za-z0-9._/-]{3,80}", prefix):
        raise WorkforcePolicyError("Use a safe branch prefix")
    attempts = max(1, min(int(max_repair_attempts), 3))
    db.execute(
        """UPDATE workforce_guardrails SET
               allowed_paths_json=?,protected_paths_json=?,protected_branches_json=?,
               branch_prefix=?,max_repair_attempts=?,updated_at=?
           WHERE user_id=?""",
        (
            _json(allowed),
            _json(protected),
            _json(branches),
            prefix,
            attempts,
            _now(),
            user_id,
        ),
    )
    db.commit()
    row = db.execute(
        "SELECT * FROM workforce_guardrails WHERE user_id=?",
        (user_id,),
    ).fetchone()
    if not row:
        raise RuntimeError("Guardrail update was not persisted")
    return row


def imported_repository(
    db: sqlite3.Connection,
    user_id: int,
    repository: str,
) -> sqlite3.Row | None:
    return db.execute(
        """SELECT * FROM repositories
           WHERE owner_id=? AND github_full_name=? COLLATE NOCASE""",
        (user_id, repository.strip()),
    ).fetchone()


def _runner_online(row: sqlite3.Row) -> bool:
    if row["revoked_at"] or row["status"] == "busy" or not row["last_seen_at"]:
        return False
    try:
        seen = datetime.fromisoformat(str(row["last_seen_at"]))
    except ValueError:
        return False
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - seen <= ONLINE_WINDOW


def eligible_edge_runners(
    db: sqlite3.Connection,
    user_id: int,
    mode: str,
) -> list[dict[str, Any]]:
    rows = db.execute(
        """SELECT * FROM task_runners
           WHERE user_id=? AND revoked_at IS NULL
           ORDER BY status='online' DESC,last_seen_at DESC,created_at""",
        (user_id,),
    ).fetchall()
    eligible: list[dict[str, Any]] = []
    for row in rows:
        capabilities = set(_loads(row["capabilities_json"], []))
        if not _runner_online(row):
            continue
        if "engineering_workforce_v1" not in capabilities:
            continue
        if mode not in capabilities and "all" not in capabilities:
            continue
        eligible.append(
            {
                "id": row["id"],
                "name": row["name"],
                "status": "online",
                "version": row["version"],
                "capabilities": sorted(capabilities),
                "labels": _loads(row["labels_json"], []),
                "system": _loads(row["system_json"], {}),
                "last_seen_at": row["last_seen_at"],
            }
        )
    return eligible


def execution_fabric(db: sqlite3.Connection, user_id: int, mode: str = "build") -> dict:
    ensure_workforce_schema(db, commit=False)
    edge = eligible_edge_runners(db, user_id, mode)
    queued = db.execute(
        """SELECT execution_target,COUNT(*) AS count FROM global_tasks
           WHERE user_id=? AND status IN ('queued','running','awaiting_approval')
           GROUP BY execution_target""",
        (user_id,),
    ).fetchall()
    load = {str(row["execution_target"]): int(row["count"]) for row in queued}
    return {
        "scheduler": "edge-first-with-safe-cloud-fallback",
        "cloud": {
            "available": True,
            "target": "github",
            "isolation": "locked-down verification runner",
            "active_tasks": load.get("github", 0) + load.get("cloud", 0),
        },
        "edge": {
            "available": bool(edge),
            "eligible_runners": edge,
            "active_tasks": load.get("self_hosted", 0),
            "required_capability": "engineering_workforce_v1",
        },
        "selection_rule": (
            "Use an online authorized edge runner that advertises the workforce contract; "
            "otherwise use the controlled GitHub/cloud execution lane."
        ),
    }


def select_execution_target(
    db: sqlite3.Connection,
    user_id: int,
    *,
    mode: str,
    preference: Literal["auto", "edge", "cloud", "github"],
) -> tuple[str, str | None, str]:
    edge = eligible_edge_runners(db, user_id, mode)
    if preference == "edge":
        if not edge:
            raise WorkforcePolicyError(
                "No online edge runner advertises engineering_workforce_v1 for this task"
            )
        return "self_hosted", edge[0]["id"], "selected requested edge runner"
    if preference in {"cloud", "github"}:
        return "github", None, "selected controlled cloud/GitHub execution"
    if edge:
        return "self_hosted", edge[0]["id"], "edge runner selected automatically"
    return "github", None, "no eligible edge runner; selected safe cloud fallback"


def delegation_plan(kind: str, acceptance_criteria: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "phase": "understand",
            "label": "Understand requirement and repository state",
            "human_required": False,
        },
        {
            "phase": "plan",
            "label": "Build a bounded implementation plan",
            "human_required": False,
        },
        {
            "phase": "execute",
            "label": f"Implement the delegated {kind} on an isolated branch",
            "human_required": False,
        },
        {
            "phase": "verify",
            "label": "Run isolated tests and self-correct within the repair limit",
            "human_required": False,
            "acceptance_criteria": acceptance_criteria,
        },
        {
            "phase": "deliver",
            "label": "Open a verified draft pull request",
            "human_required": True,
            "decision": "final review and merge",
        },
    ]


def build_delegation_objective(
    *,
    delegation_id: str,
    kind: str,
    title: str,
    requirement: str,
    source_reference: str | None,
    acceptance_criteria: list[str],
    guardrails: dict[str, Any],
) -> str:
    criteria = "\n".join(f"- {item}" for item in acceptance_criteria)
    source = source_reference or "direct product requirement"
    return (
        "# Amosclaud Autonomous Engineering Workforce Delegation\n\n"
        f"Delegation: {delegation_id}\n"
        f"Work item: {title}\n"
        f"Type: {kind}\n"
        f"Source: {source}\n\n"
        "## Requirement\n"
        f"{requirement.strip()}\n\n"
        "## Acceptance criteria\n"
        f"{criteria}\n\n"
        "## Required autonomous lifecycle\n"
        "Plan -> Execute -> Test -> Diagnose -> Self-correct -> Verify -> Draft pull request.\n\n"
        "## Immutable safety contract\n"
        "- Work only inside the selected connected repository.\n"
        "- Create an isolated work branch; never write directly to a protected branch.\n"
        "- Run deterministic isolated verification before claiming success.\n"
        f"- Maximum repair attempts: {guardrails['max_repair_attempts']}.\n"
        "- Never force-push and never merge automatically.\n"
        "- Open a draft pull request and wait for human final sign-off.\n"
        "- Mask credentials and do not include secrets in commits, logs, or agent output.\n"
        "- Record the base revision as the rollback checkpoint.\n"
        "- Allowed paths: " + ", ".join(guardrails["allowed_paths"]) + "\n"
        "- Protected paths: " + ", ".join(guardrails["protected_paths"])
    )[:20_000]


def add_delegation_event(
    db: sqlite3.Connection,
    delegation_id: str,
    event_type: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    db.execute(
        """INSERT INTO workforce_delegation_events(
               delegation_id,event_type,message,details_json,created_at
           ) VALUES (?,?,?,?,?)""",
        (delegation_id, event_type, redact(message), _json(details or {}), _now()),
    )


def delegation_dict(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["acceptance_criteria"] = _loads(item.pop("acceptance_criteria_json"), [])
    item["guardrails"] = _loads(item.pop("guardrails_json"), {})
    item["plan"] = _loads(item.pop("plan_json"), [])
    task = None
    if item.get("task_id"):
        task_row = db.execute(
            "SELECT * FROM global_tasks WHERE id=? AND user_id=?",
            (item["task_id"], item["user_id"]),
        ).fetchone()
        if task_row:
            task = task_router._task_dict(task_row)
            item["status"] = str(task["status"])
            item["updated_at"] = (
                task.get("finished_at")
                or task.get("started_at")
                or task.get("approved_at")
                or item["updated_at"]
            )
    item["task"] = task
    item["human_attention_required"] = item["status"] in {
        "awaiting_approval",
        "failed",
        "blocked",
        "completed",
    }
    if item["status"] == "completed":
        item["human_attention_reason"] = "Review the verified draft pull request and decide whether to merge."
    elif item["status"] == "awaiting_approval":
        item["human_attention_reason"] = "Authorize repository changes before execution."
    elif item["status"] in {"failed", "blocked"}:
        item["human_attention_reason"] = "The autonomous loop stopped safely and needs judgment."
    else:
        item["human_attention_reason"] = None
    return item


def record_delegation_task_event(
    task_id: str,
    status: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Record workforce lifecycle evidence without requiring the runner to own a DB handle."""

    from amoscloud_ai.api.routes.auth import _connect

    with _connect() as db:
        ensure_workforce_schema(db, commit=False)
        row = db.execute(
            "SELECT id FROM workforce_delegations WHERE task_id=?",
            (task_id,),
        ).fetchone()
        if not row:
            db.commit()
            return
        normalized = status if status in DELEGATION_STATUSES else "running"
        db.execute(
            "UPDATE workforce_delegations SET status=?,updated_at=? WHERE id=?",
            (normalized, _now(), row["id"]),
        )
        add_delegation_event(db, row["id"], f"task.{normalized}", message, details)
        db.commit()


def validate_target_url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    target = value.strip()
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise WorkforcePolicyError("Asset target URL must use http or https")
    if parsed.username or parsed.password:
        raise WorkforcePolicyError("Asset target URL must not contain credentials")
    return target


def create_asset_token() -> tuple[str, str, str]:
    token = "amos_asset_" + secrets.token_urlsafe(36)
    return token, _hash(token), token[:20]


def authenticate_asset(db: sqlite3.Connection, asset_id: str, authorization: str | None) -> sqlite3.Row:
    if not authorization or not authorization.startswith("Bearer "):
        raise WorkforcePolicyError("Asset telemetry credential required")
    raw = authorization.removeprefix("Bearer ").strip()
    row = db.execute("SELECT * FROM software_assets WHERE id=?", (asset_id,)).fetchone()
    if not row or not secrets.compare_digest(str(row["telemetry_token_hash"]), _hash(raw)):
        raise WorkforcePolicyError("Asset telemetry credential is invalid")
    return row


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def asset_health(db: sqlite3.Connection, asset: sqlite3.Row) -> dict[str, Any]:
    samples = db.execute(
        """SELECT * FROM software_asset_telemetry
           WHERE asset_id=? ORDER BY observed_at DESC,id DESC LIMIT 288""",
        (asset["id"],),
    ).fetchall()
    latest = dict(samples[0]) if samples else None
    now = datetime.now(timezone.utc)
    recent = [
        row
        for row in samples
        if (_parse_time(row["observed_at"]) or datetime.min.replace(tzinfo=timezone.utc))
        >= now - timedelta(hours=24)
    ]
    if not latest:
        state = "unknown"
    else:
        observed = _parse_time(latest["observed_at"])
        if not observed or now - observed > ASSET_STALE_WINDOW:
            state = "stale"
        elif not bool(latest["online"]):
            state = "offline"
        elif int(latest.get("error_count") or 0) > 0 or int(latest.get("status_code") or 0) >= 500:
            state = "degraded"
        else:
            state = "operational"

    uptime = None
    average_latency = None
    if recent:
        uptime = round(100 * sum(int(row["online"]) for row in recent) / len(recent), 2)
        latencies = [float(row["latency_ms"]) for row in recent if row["latency_ms"] is not None]
        if latencies:
            average_latency = round(sum(latencies) / len(latencies), 2)

    repository = str(asset["repository"] or "")
    patch_rows = []
    if repository:
        patch_rows = db.execute(
            """SELECT status FROM global_tasks
               WHERE user_id=? AND repository=? COLLATE NOCASE
                 AND mode IN ('build','fix') AND status IN ('completed','failed')""",
            (asset["user_id"], repository),
        ).fetchall()
    patch_completed = sum(1 for row in patch_rows if row["status"] == "completed")
    patch_failed = sum(1 for row in patch_rows if row["status"] == "failed")
    patch_total = patch_completed + patch_failed

    return {
        "state": state,
        "latest": latest,
        "window_24h": {
            "samples": len(recent),
            "uptime_percent": uptime,
            "average_latency_ms": average_latency,
            "errors": sum(int(row["error_count"] or 0) for row in recent),
            "requests": sum(int(row["request_count"] or 0) for row in recent),
        },
        "business": {
            "active_users": latest.get("active_users") if latest else None,
            "revenue_usd": (
                round(int(latest["revenue_cents"]) / 100, 2)
                if latest and latest.get("revenue_cents") is not None
                else None
            ),
        },
        "autonomous_maintenance": {
            "completed_patches": patch_completed,
            "failed_patches": patch_failed,
            "patch_success_rate": (
                round(100 * patch_completed / patch_total, 2) if patch_total else None
            ),
        },
    }


def asset_dict(db: sqlite3.Connection, row: sqlite3.Row, *, include_health: bool = True) -> dict:
    item = {
        key: value
        for key, value in dict(row).items()
        if key not in {"telemetry_token_hash"}
    }
    if include_health:
        item["health"] = asset_health(db, row)
    return item


def workforce_overview(db: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    ensure_workforce_schema(db, commit=False)
    delegations = db.execute(
        """SELECT * FROM workforce_delegations
           WHERE user_id=? ORDER BY created_at DESC LIMIT 12""",
        (user_id,),
    ).fetchall()
    assets = db.execute(
        """SELECT * FROM software_assets
           WHERE user_id=? ORDER BY updated_at DESC LIMIT 12""",
        (user_id,),
    ).fetchall()
    status_rows = db.execute(
        """SELECT status,COUNT(*) AS count FROM global_tasks
           WHERE user_id=? GROUP BY status""",
        (user_id,),
    ).fetchall()
    return {
        "vision": "Autonomous software ownership with human judgment at approval and final sign-off.",
        "task_counts": {str(row["status"]): int(row["count"]) for row in status_rows},
        "delegations": [delegation_dict(db, row) for row in delegations],
        "assets": [asset_dict(db, row) for row in assets],
        "execution_fabric": execution_fabric(db, user_id),
        "guardrails": guardrail_dict(ensure_guardrails(db, user_id, commit=False)),
    }
