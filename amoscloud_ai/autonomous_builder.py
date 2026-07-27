"""Durable, policy-bounded daily feature builder for Amosclaud.

The builder selects one small backlog item, creates a deterministic technical
specification, and routes the work through the existing Global Task Router. It
never writes directly to a repository, never merges a pull request, and remains
disabled unless both the server environment and the account setting allow it.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from amoscloud_ai.agent_tokens import debit_tokens
from amoscloud_ai.api.routes.auth import _connect
from amoscloud_ai.api.routes.operation_buckets import ensure_user_bucket

DEFAULT_ALLOWED_PATHS = (
    "amoscloud_ai",
    "docs",
    "pages-site",
    "tests",
    "web",
)
DEFAULT_PROTECTED_PATHS = (
    ".env",
    ".github",
    "amoscloud_ai/api/routes/auth.py",
    "amoscloud_ai/api/routes/billing.py",
    "amoscloud_ai/api/routes/service_keys.py",
    "amoscloud_ai/db_migrations.py",
    "config",
    "docker-compose.yml",
    "docker-compose.workspace-runtime.yml",
    "services",
)
BACKLOG_STATUSES = {"proposed", "selected", "running", "completed", "rejected", "blocked"}
RUN_STATUSES = {"planning", "queued", "running", "completed", "failed", "blocked", "cancelled"}


class AutonomousPolicyError(RuntimeError):
    """Raised when autonomous work crosses an account policy boundary."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def environment_enabled() -> bool:
    """Return true only when the server-level autonomy switch is explicitly on."""

    enabled = os.getenv("AMOSCLAUD_AUTONOMY_ENABLED", "false").strip().lower()
    paused = os.getenv("AMOSCLAUD_AUTONOMY_PAUSED", "false").strip().lower()
    return enabled in {"1", "true", "yes", "on"} and paused not in {
        "1",
        "true",
        "yes",
        "on",
    }


def ensure_autonomy_schema(db: sqlite3.Connection, *, commit: bool = True) -> None:
    """Create the autonomous builder ledger idempotently."""

    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS autonomy_settings (
            user_id INTEGER PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
            daily_limit INTEGER NOT NULL DEFAULT 1 CHECK(daily_limit BETWEEN 1 AND 3),
            max_repair_attempts INTEGER NOT NULL DEFAULT 3
                CHECK(max_repair_attempts BETWEEN 1 AND 3),
            allowed_repositories_json TEXT NOT NULL DEFAULT '[]',
            allowed_paths_json TEXT NOT NULL DEFAULT '[]',
            protected_paths_json TEXT NOT NULL DEFAULT '[]',
            staging_required INTEGER NOT NULL DEFAULT 1 CHECK(staging_required IN (0,1)),
            auto_merge INTEGER NOT NULL DEFAULT 0 CHECK(auto_merge = 0),
            last_run_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS autonomous_backlog (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            repository TEXT NOT NULL,
            title TEXT NOT NULL,
            objective TEXT NOT NULL,
            source TEXT NOT NULL,
            acceptance_criteria_json TEXT NOT NULL,
            user_value INTEGER NOT NULL,
            roadmap_alignment INTEGER NOT NULL,
            recurring_failure_reduction INTEGER NOT NULL,
            maintainability_improvement INTEGER NOT NULL,
            implementation_risk INTEGER NOT NULL,
            security_risk INTEGER NOT NULL,
            estimated_size INTEGER NOT NULL,
            score INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'proposed',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS autonomous_runs (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            backlog_id TEXT NOT NULL,
            task_id TEXT,
            repository TEXT NOT NULL,
            status TEXT NOT NULL,
            specification TEXT NOT NULL,
            summary TEXT,
            pull_request_url TEXT,
            verification_id TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(backlog_id) REFERENCES autonomous_backlog(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS autonomous_run_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES autonomous_runs(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_autonomous_backlog_owner_status_score
            ON autonomous_backlog(user_id, status, score DESC, created_at);
        CREATE INDEX IF NOT EXISTS idx_autonomous_runs_owner_created
            ON autonomous_runs(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_autonomous_runs_task
            ON autonomous_runs(task_id);
        CREATE INDEX IF NOT EXISTS idx_autonomous_run_events_run
            ON autonomous_run_events(run_id, id);
        """
    )
    if commit:
        db.commit()


def ensure_settings(db: sqlite3.Connection, user_id: int, *, commit: bool = True) -> sqlite3.Row:
    ensure_autonomy_schema(db, commit=False)
    now = _now()
    db.execute(
        """INSERT OR IGNORE INTO autonomy_settings(
               user_id,enabled,daily_limit,max_repair_attempts,
               allowed_repositories_json,allowed_paths_json,protected_paths_json,
               staging_required,auto_merge,created_at,updated_at
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            user_id,
            0,
            1,
            3,
            "[]",
            _json(DEFAULT_ALLOWED_PATHS),
            _json(DEFAULT_PROTECTED_PATHS),
            1,
            0,
            now,
            now,
        ),
    )
    row = db.execute("SELECT * FROM autonomy_settings WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        raise RuntimeError("Unable to provision autonomy settings")
    if commit:
        db.commit()
    return row


def settings_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["enabled"] = bool(item["enabled"])
    item["staging_required"] = bool(item["staging_required"])
    item["auto_merge"] = bool(item["auto_merge"])
    item["allowed_repositories"] = _loads(item.pop("allowed_repositories_json"), [])
    item["allowed_paths"] = _loads(item.pop("allowed_paths_json"), [])
    item["protected_paths"] = _loads(item.pop("protected_paths_json"), [])
    item["environment_enabled"] = environment_enabled()
    return item


def score_candidate(item: dict[str, Any] | sqlite3.Row) -> int:
    """Score a feature deterministically; higher value and lower risk win."""

    positive = sum(
        int(item[name])
        for name in (
            "user_value",
            "roadmap_alignment",
            "recurring_failure_reduction",
            "maintainability_improvement",
        )
    )
    negative = sum(
        int(item[name])
        for name in ("implementation_risk", "security_risk", "estimated_size")
    )
    return positive - negative


def _clean_prefix(value: str) -> str:
    candidate = str(value or "").strip().replace("\\", "/").strip("/")
    path = PurePosixPath(candidate)
    if not candidate or path.is_absolute() or ".." in path.parts:
        raise AutonomousPolicyError(f"Invalid autonomous path policy: {value!r}")
    return path.as_posix()


def normalize_prefixes(values: list[str] | tuple[str, ...]) -> list[str]:
    return sorted({_clean_prefix(value) for value in values})


def _matches(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def path_policy_violations(
    changed_files: list[str],
    *,
    allowed_paths: list[str],
    protected_paths: list[str],
) -> list[str]:
    """Return deterministic policy violations for changed repository paths."""

    allowed = normalize_prefixes(allowed_paths)
    protected = normalize_prefixes([*DEFAULT_PROTECTED_PATHS, *protected_paths])
    if not allowed:
        return ["No autonomous write paths are configured"]
    violations: list[str] = []
    for raw in changed_files:
        try:
            path = _clean_prefix(raw)
        except AutonomousPolicyError:
            violations.append(f"Unsafe changed path: {raw}")
            continue
        if any(_matches(path, prefix) for prefix in protected):
            violations.append(f"Protected path changed: {path}")
            continue
        if not any(_matches(path, prefix) for prefix in allowed):
            violations.append(f"Path is outside the autonomous allowlist: {path}")
    return violations


def task_policy(task: dict[str, Any]) -> dict[str, Any] | None:
    metadata = task.get("metadata")
    if metadata is None:
        metadata = _loads(task.get("metadata_json"), {})
    if not isinstance(metadata, dict) or metadata.get("autonomous_builder") is not True:
        return None
    return metadata


def enforce_task_path_policy(task: dict[str, Any], changed_files: list[str]) -> None:
    policy = task_policy(task)
    if not policy or not changed_files:
        return
    violations = path_policy_violations(
        changed_files,
        allowed_paths=list(policy.get("allowed_paths") or []),
        protected_paths=list(policy.get("protected_paths") or []),
    )
    if violations:
        raise AutonomousPolicyError(
            "Autonomous policy blocked publication: " + "; ".join(violations[:8])
        )


def build_specification(item: sqlite3.Row, settings: sqlite3.Row) -> str:
    criteria = _loads(item["acceptance_criteria_json"], [])
    allowed = _loads(settings["allowed_paths_json"], list(DEFAULT_ALLOWED_PATHS))
    protected = normalize_prefixes(
        [*DEFAULT_PROTECTED_PATHS, *_loads(settings["protected_paths_json"], [])]
    )
    lines = [
        "# Amosclaud Daily Autonomous Feature Specification",
        "",
        f"Feature: {item['title']}",
        f"Repository: {item['repository']}",
        f"Objective: {item['objective']}",
        f"Source: {item['source']}",
        "",
        "## Acceptance criteria",
    ]
    lines.extend(f"- {criterion}" for criterion in criteria)
    lines.extend(
        [
            "",
            "## Mandatory execution policy",
            "- Make the smallest reversible change that satisfies the criteria.",
            "- Add or update focused tests for changed behavior.",
            "- Run deterministic isolated verification before publication.",
            "- Never push directly to main and never merge automatically.",
            "- Publish only a draft pull request.",
            f"- Maximum repair attempts: {settings['max_repair_attempts']}.",
            f"- Staging or preview validation required: {bool(settings['staging_required'])}.",
            "- Allowed paths: " + ", ".join(allowed),
            "- Protected paths: " + ", ".join(protected),
        ]
    )
    return "\n".join(lines)[:18_000]


def _event(
    db: sqlite3.Connection,
    run_id: str,
    event_type: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    db.execute(
        """INSERT INTO autonomous_run_events(
               run_id,event_type,message,details_json,created_at
           ) VALUES (?,?,?,?,?)""",
        (run_id, event_type, message, _json(details or {}), _now()),
    )


def _repository_is_imported(db: sqlite3.Connection, user_id: int, repository: str) -> bool:
    row = db.execute(
        """SELECT 1 FROM repositories
           WHERE owner_id=? AND github_full_name=? COLLATE NOCASE""",
        (user_id, repository),
    ).fetchone()
    return bool(row)


def run_daily_for_user(user_id: int) -> dict[str, Any]:
    """Select and queue the next safe backlog item for one account."""

    from amoscloud_ai.api.routes.task_router import (
        TaskCreate,
        _ensure_schema as ensure_task_schema,
        _event as task_event,
        _json as task_json,
        _now as task_now,
        _task_cost,
    )

    if not environment_enabled():
        return {"queued": [], "reason": "server_kill_switch"}

    queued: list[str] = []
    with _connect() as db:
        ensure_task_schema(db)
        ensure_autonomy_schema(db, commit=False)
        settings = ensure_settings(db, user_id, commit=False)
        if not bool(settings["enabled"]):
            db.commit()
            return {"queued": [], "reason": "account_disabled"}
        allowed_repositories = list(_loads(settings["allowed_repositories_json"], []))
        if not allowed_repositories:
            db.commit()
            return {"queued": [], "reason": "no_allowed_repositories"}

        today = datetime.now(timezone.utc).date().isoformat()
        used = int(
            db.execute(
                """SELECT COUNT(*) FROM autonomous_runs
                   WHERE user_id=? AND substr(created_at,1,10)=?
                     AND status NOT IN ('blocked','cancelled')""",
                (user_id, today),
            ).fetchone()[0]
        )
        remaining = max(0, int(settings["daily_limit"]) - used)
        if not remaining:
            db.commit()
            return {"queued": [], "reason": "daily_limit_reached"}

        placeholders = ",".join("?" for _ in allowed_repositories)
        candidates = db.execute(
            f"""SELECT * FROM autonomous_backlog
                WHERE user_id=? AND status='proposed'
                  AND repository IN ({placeholders})
                  AND implementation_risk <= 5
                  AND security_risk <= 3
                  AND estimated_size <= 5
                ORDER BY score DESC, created_at ASC LIMIT ?""",
            (user_id, *allowed_repositories, remaining),
        ).fetchall()

        for item in candidates:
            run_id = "autorun_" + uuid.uuid4().hex
            specification = build_specification(item, settings)
            now = _now()
            db.execute(
                """INSERT INTO autonomous_runs(
                       id,user_id,backlog_id,repository,status,specification,created_at
                   ) VALUES (?,?,?,?,?,?,?)""",
                (run_id, user_id, item["id"], item["repository"], "planning", specification, now),
            )
            _event(
                db,
                run_id,
                "idea.selected",
                "Selected the highest-scoring eligible backlog item.",
                {"backlog_id": item["id"], "score": item["score"]},
            )

            if not _repository_is_imported(db, user_id, item["repository"]):
                db.execute(
                    "UPDATE autonomous_runs SET status='blocked',summary=?,finished_at=? WHERE id=?",
                    ("Repository is not imported through the connected GitHub account.", now, run_id),
                )
                db.execute(
                    "UPDATE autonomous_backlog SET status='blocked',updated_at=? WHERE id=?",
                    (now, item["id"]),
                )
                _event(db, run_id, "run.blocked", "Connected GitHub repository is unavailable.")
                continue

            task_id = "task_" + uuid.uuid4().hex
            metadata = {
                "autonomous_builder": True,
                "autonomous_run_id": run_id,
                "autonomous_backlog_id": item["id"],
                "allowed_paths": _loads(settings["allowed_paths_json"], []),
                "protected_paths": _loads(settings["protected_paths_json"], []),
                "max_repair_attempts": int(settings["max_repair_attempts"]),
                "staging_required": bool(settings["staging_required"]),
                "auto_merge": False,
                "specification_version": 1,
            }
            body = TaskCreate(
                objective=specification,
                repository=item["repository"],
                mode="build",
                delivery="pull_request",
                execution_target="github",
                require_approval=False,
                metadata=metadata,
            )
            cost = _task_cost(body)
            if not debit_tokens(db, user_id, cost, reference=task_id):
                db.execute(
                    "UPDATE autonomous_runs SET status='blocked',summary=?,finished_at=? WHERE id=?",
                    ("Agent tokens are required before autonomous work can start.", now, run_id),
                )
                db.execute(
                    "UPDATE autonomous_backlog SET status='blocked',updated_at=? WHERE id=?",
                    (now, item["id"]),
                )
                _event(db, run_id, "run.blocked", "Insufficient agent tokens.")
                continue

            bucket = ensure_user_bucket(db, user_id, commit=False)
            db.execute(
                """INSERT INTO global_tasks(
                       id,user_id,bucket_id,repository,objective,mode,delivery,status,
                       execution_target,runner_id,require_approval,reserved_credits,
                       metadata_json,created_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task_id,
                    user_id,
                    bucket["id"],
                    item["repository"],
                    specification,
                    "build",
                    "pull_request",
                    "queued",
                    "github",
                    None,
                    0,
                    cost,
                    task_json(metadata),
                    task_now(),
                ),
            )
            task_event(
                db,
                task_id,
                "task.created",
                "Daily Autonomous Builder queued a policy-bounded draft-PR task.",
                {"autonomous_run_id": run_id, "credits_reserved": cost},
            )
            db.execute(
                """UPDATE autonomous_runs
                   SET task_id=?,status='queued',started_at=? WHERE id=?""",
                (task_id, now, run_id),
            )
            db.execute(
                "UPDATE autonomous_backlog SET status='running',updated_at=? WHERE id=?",
                (now, item["id"]),
            )
            _event(
                db,
                run_id,
                "task.queued",
                "Routed the specification to the existing isolated GitHub task runner.",
                {"task_id": task_id, "bucket_id": bucket["id"]},
            )
            queued.append(task_id)

        if queued:
            db.execute(
                "UPDATE autonomy_settings SET last_run_at=?,updated_at=? WHERE user_id=?",
                (_now(), _now(), user_id),
            )
        db.commit()

    from amoscloud_ai.cloud_task_runner import dispatch_cloud_task

    for task_id in queued:
        dispatch_cloud_task(task_id)
    return {"queued": queued, "count": len(queued), "reason": None if queued else "no_eligible_items"}


def run_enabled_users() -> dict[str, Any]:
    """Run the once-daily selection pass for every enabled account."""

    if not environment_enabled():
        return {"users": 0, "queued": 0, "reason": "server_kill_switch"}
    with _connect() as db:
        ensure_autonomy_schema(db)
        user_ids = [
            int(row[0])
            for row in db.execute(
                "SELECT user_id FROM autonomy_settings WHERE enabled=1 ORDER BY user_id"
            ).fetchall()
        ]
    total = 0
    results: dict[str, Any] = {}
    for user_id in user_ids:
        result = run_daily_for_user(user_id)
        total += int(result.get("count") or 0)
        results[str(user_id)] = result
    return {"users": len(user_ids), "queued": total, "results": results}


def record_task_started(task_id: str) -> None:
    with _connect() as db:
        ensure_autonomy_schema(db, commit=False)
        row = db.execute(
            "SELECT metadata_json FROM global_tasks WHERE id=?", (task_id,)
        ).fetchone()
        metadata = _loads(row["metadata_json"], {}) if row else {}
        run_id = metadata.get("autonomous_run_id") if isinstance(metadata, dict) else None
        if not run_id:
            db.commit()
            return
        now = _now()
        db.execute(
            "UPDATE autonomous_runs SET status='running',started_at=COALESCE(started_at,?) WHERE id=?",
            (now, run_id),
        )
        _event(db, run_id, "task.started", "The isolated engineering task started.", {"task_id": task_id})
        db.commit()


def record_task_completion(
    task_id: str,
    status: str,
    summary: str,
    *,
    pull_request_url: str | None = None,
    verification_id: str | None = None,
) -> None:
    with _connect() as db:
        ensure_autonomy_schema(db, commit=False)
        task = db.execute(
            "SELECT metadata_json FROM global_tasks WHERE id=?", (task_id,)
        ).fetchone()
        metadata = _loads(task["metadata_json"], {}) if task else {}
        run_id = metadata.get("autonomous_run_id") if isinstance(metadata, dict) else None
        if not run_id:
            db.commit()
            return
        run = db.execute("SELECT * FROM autonomous_runs WHERE id=?", (run_id,)).fetchone()
        if not run:
            db.commit()
            return
        final_status = "completed" if status == "completed" else "failed"
        if "policy blocked" in summary.lower():
            final_status = "blocked"
        now = _now()
        db.execute(
            """UPDATE autonomous_runs
               SET status=?,summary=?,pull_request_url=?,verification_id=?,finished_at=?
               WHERE id=?""",
            (final_status, summary[:20_000], pull_request_url, verification_id, now, run_id),
        )
        backlog_status = "completed" if final_status == "completed" else "blocked"
        db.execute(
            "UPDATE autonomous_backlog SET status=?,updated_at=? WHERE id=?",
            (backlog_status, now, run["backlog_id"]),
        )
        _event(
            db,
            run_id,
            f"run.{final_status}",
            summary[:20_000],
            {
                "task_id": task_id,
                "pull_request_url": pull_request_url,
                "verification_id": verification_id,
            },
        )
        db.commit()
