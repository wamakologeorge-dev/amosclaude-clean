"""Durable multi-service cooperation for Amosclaud pipeline work.

This module is deliberately additive.  It does not replace the existing pipeline
API; it gives agents, self-hosted runners, verification services, and future
control-plane modules one shared task, approval, artifact, and event contract.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes import auth, repositories

router = APIRouter(tags=["pipeline-cooperation"])
_LOCK = threading.RLock()


class CooperationPipelineState(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CooperationTaskState(str, Enum):
    BLOCKED = "blocked"
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CooperationApprovalState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


PipelineMode = Literal["inspect", "build", "fix", "deploy", "monitor"]


class CooperationPipelineCreate(BaseModel):
    objective: str = Field(..., min_length=1, max_length=12_000)
    mode: PipelineMode = "inspect"
    repository_id: int | None = Field(default=None, ge=1)
    project_id: str | None = Field(default=None, max_length=200)
    environment: Literal["development", "preview", "staging", "production"] = "development"
    branch: str = Field(default="main", min_length=1, max_length=200)
    allow_writes: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class CooperationWorkerRegister(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    capabilities: list[str] = Field(..., min_length=1, max_length=100)
    capacity: int = Field(default=1, ge=1, le=100)
    endpoint: str | None = Field(default=None, max_length=2_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CooperationWorkerHeartbeat(BaseModel):
    status: Literal["ready", "busy", "draining", "offline"] = "ready"
    active_tasks: int | None = Field(default=None, ge=0, le=100_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CooperationTaskResult(BaseModel):
    worker_id: str | None = Field(default=None, max_length=200)
    summary: str = Field(default="", max_length=20_000)
    output: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class CooperationTaskFailure(BaseModel):
    worker_id: str | None = Field(default=None, max_length=200)
    error: str = Field(..., min_length=1, max_length=20_000)
    retryable: bool = False


class CooperationApprovalDecision(BaseModel):
    reason: str = Field(default="", max_length=5_000)


CONTROL_PLANE_MODULES: tuple[dict[str, str], ...] = (
    {"key": "flags", "name": "Flags", "status": "foundation"},
    {"key": "agent", "name": "Agent", "status": "active"},
    {"key": "ai_gateway", "name": "AI Gateway", "status": "foundation"},
    {"key": "sandboxes", "name": "Sandboxes", "status": "foundation"},
    {"key": "workflows", "name": "Workflows", "status": "active"},
    {"key": "images", "name": "Images", "status": "planned"},
    {"key": "usage", "name": "Usage", "status": "foundation"},
    {"key": "support", "name": "Support", "status": "foundation"},
    {"key": "settings", "name": "Settings", "status": "active"},
    {"key": "logs", "name": "Logs", "status": "pending-integration"},
    {"key": "analytics", "name": "Analytics", "status": "foundation"},
    {"key": "speed_insights", "name": "Speed Insights", "status": "planned"},
    {"key": "observability", "name": "Observability", "status": "foundation"},
    {"key": "firewall", "name": "Firewall", "status": "foundation"},
    {"key": "cdn", "name": "CDN", "status": "planned"},
    {
        "key": "environment_variables",
        "name": "Environment Variables",
        "status": "foundation",
    },
    {"key": "domains", "name": "Domains", "status": "active"},
    {"key": "connect", "name": "Connect", "status": "foundation"},
    {"key": "integrations", "name": "Integrations", "status": "foundation"},
    {"key": "storage", "name": "Storage", "status": "active"},
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _db() -> sqlite3.Connection:
    auth.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(auth.DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS cooperation_pipeline_runs (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            repository_id INTEGER,
            project_id TEXT,
            objective TEXT NOT NULL,
            mode TEXT NOT NULL,
            environment TEXT NOT NULL,
            branch TEXT NOT NULL,
            state TEXT NOT NULL,
            allow_writes INTEGER NOT NULL DEFAULT 0,
            repository_role TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            error_detail TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_cooperation_pipeline_user_created
            ON cooperation_pipeline_runs(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_cooperation_pipeline_repository
            ON cooperation_pipeline_runs(user_id, repository_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS cooperation_tasks (
            id TEXT PRIMARY KEY,
            pipeline_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            task_key TEXT NOT NULL,
            name TEXT NOT NULL,
            capability TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            state TEXT NOT NULL,
            requires_approval INTEGER NOT NULL DEFAULT 0,
            depends_on_json TEXT NOT NULL DEFAULT '[]',
            input_json TEXT NOT NULL DEFAULT '{}',
            output_json TEXT NOT NULL DEFAULT '{}',
            claimed_by_worker_id TEXT,
            attempt INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            error_detail TEXT NOT NULL DEFAULT '',
            UNIQUE(pipeline_id, task_key),
            FOREIGN KEY(pipeline_id) REFERENCES cooperation_pipeline_runs(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_cooperation_tasks_ready
            ON cooperation_tasks(user_id, state, sequence, created_at);
        CREATE INDEX IF NOT EXISTS idx_cooperation_tasks_pipeline
            ON cooperation_tasks(pipeline_id, sequence);

        CREATE TABLE IF NOT EXISTS cooperation_workers (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            capabilities_json TEXT NOT NULL,
            status TEXT NOT NULL,
            capacity INTEGER NOT NULL,
            active_tasks INTEGER NOT NULL DEFAULT 0,
            endpoint TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_heartbeat TEXT NOT NULL,
            UNIQUE(user_id, name)
        );
        CREATE INDEX IF NOT EXISTS idx_cooperation_workers_user_status
            ON cooperation_workers(user_id, status, last_heartbeat DESC);

        CREATE TABLE IF NOT EXISTS cooperation_approvals (
            id TEXT PRIMARY KEY,
            pipeline_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            state TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            decided_at TEXT,
            FOREIGN KEY(pipeline_id) REFERENCES cooperation_pipeline_runs(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_cooperation_approvals_pipeline
            ON cooperation_approvals(pipeline_id, state);

        CREATE TABLE IF NOT EXISTS cooperation_artifacts (
            id TEXT PRIMARY KEY,
            pipeline_id TEXT NOT NULL,
            task_id TEXT,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            uri TEXT NOT NULL,
            sha256 TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(pipeline_id) REFERENCES cooperation_pipeline_runs(id) ON DELETE CASCADE,
            FOREIGN KEY(task_id) REFERENCES cooperation_tasks(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cooperation_artifacts_pipeline
            ON cooperation_artifacts(pipeline_id, created_at);

        CREATE TABLE IF NOT EXISTS cooperation_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            pipeline_id TEXT NOT NULL,
            task_id TEXT,
            user_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(pipeline_id) REFERENCES cooperation_pipeline_runs(id) ON DELETE CASCADE,
            FOREIGN KEY(task_id) REFERENCES cooperation_tasks(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cooperation_events_pipeline
            ON cooperation_events(pipeline_id, sequence);
        """
    )
    db.commit()
    return db


def _current_user(amos_session: str | None = Cookie(default=None)) -> sqlite3.Row:
    user = auth.get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _is_admin(user: sqlite3.Row | dict[str, Any]) -> bool:
    try:
        return bool(user["is_admin"])
    except (KeyError, IndexError, TypeError):
        return False


def _event(
    db: sqlite3.Connection,
    *,
    pipeline_id: str,
    user_id: int,
    event_type: str,
    task_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    db.execute(
        """INSERT INTO cooperation_events(
            pipeline_id,task_id,user_id,event_type,payload_json,created_at
        ) VALUES (?,?,?,?,?,?)""",
        (pipeline_id, task_id, user_id, event_type, _json(payload or {}), _now()),
    )


def _pipeline_row(
    db: sqlite3.Connection,
    pipeline_id: str,
    user_id: int,
    *,
    administrator: bool = False,
) -> sqlite3.Row:
    if administrator:
        row = db.execute(
            "SELECT * FROM cooperation_pipeline_runs WHERE id=?", (pipeline_id,)
        ).fetchone()
    else:
        row = db.execute(
            "SELECT * FROM cooperation_pipeline_runs WHERE id=? AND user_id=?",
            (pipeline_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Cooperation pipeline not found")
    return row


def _task_row(
    db: sqlite3.Connection,
    task_id: str,
    user_id: int,
    *,
    administrator: bool = False,
) -> sqlite3.Row:
    if administrator:
        row = db.execute("SELECT * FROM cooperation_tasks WHERE id=?", (task_id,)).fetchone()
    else:
        row = db.execute(
            "SELECT * FROM cooperation_tasks WHERE id=? AND user_id=?", (task_id, user_id)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Cooperation task not found")
    return row


def _approval_granted(db: sqlite3.Connection, pipeline_id: str) -> bool:
    return (
        db.execute(
            """SELECT 1 FROM cooperation_approvals
               WHERE pipeline_id=? AND state='approved' LIMIT 1""",
            (pipeline_id,),
        ).fetchone()
        is not None
    )


def _dependencies_complete(db: sqlite3.Connection, task: sqlite3.Row) -> bool:
    dependencies = _loads(task["depends_on_json"], [])
    if not dependencies:
        return True
    placeholders = ",".join("?" for _ in dependencies)
    rows = db.execute(
        f"SELECT id,state FROM cooperation_tasks WHERE id IN ({placeholders})",
        tuple(dependencies),
    ).fetchall()
    states = {row["id"]: row["state"] for row in rows}
    return all(states.get(task_id) == CooperationTaskState.COMPLETED.value for task_id in dependencies)


def _release_ready_tasks(db: sqlite3.Connection, pipeline_id: str) -> int:
    approval_granted = _approval_granted(db, pipeline_id)
    tasks = db.execute(
        """SELECT * FROM cooperation_tasks
           WHERE pipeline_id=? AND state='blocked' ORDER BY sequence""",
        (pipeline_id,),
    ).fetchall()
    released = 0
    now = _now()
    for task in tasks:
        if task["requires_approval"] and not approval_granted:
            continue
        if not _dependencies_complete(db, task):
            continue
        db.execute(
            "UPDATE cooperation_tasks SET state='queued',updated_at=? WHERE id=?",
            (now, task["id"]),
        )
        released += 1
        _event(
            db,
            pipeline_id=pipeline_id,
            task_id=task["id"],
            user_id=int(task["user_id"]),
            event_type="task.queued",
            payload={"capability": task["capability"], "name": task["name"]},
        )
    return released


def _refresh_pipeline_state(db: sqlite3.Connection, pipeline_id: str) -> str:
    pipeline = db.execute(
        "SELECT * FROM cooperation_pipeline_runs WHERE id=?", (pipeline_id,)
    ).fetchone()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Cooperation pipeline not found")
    if pipeline["state"] == CooperationPipelineState.CANCELLED.value:
        return pipeline["state"]

    tasks = db.execute(
        "SELECT task_key,state,requires_approval FROM cooperation_tasks WHERE pipeline_id=?",
        (pipeline_id,),
    ).fetchall()
    states = [task["state"] for task in tasks]
    old_state = pipeline["state"]
    finished_at: str | None = None
    if any(state == CooperationTaskState.FAILED.value for state in states):
        new_state = CooperationPipelineState.FAILED.value
        finished_at = _now()
    elif tasks and all(state == CooperationTaskState.COMPLETED.value for state in states):
        new_state = CooperationPipelineState.COMPLETED.value
        finished_at = _now()
    elif any(
        task["task_key"] in {"security", "verify"}
        and task["state"]
        in {
            CooperationTaskState.QUEUED.value,
            CooperationTaskState.CLAIMED.value,
            CooperationTaskState.RUNNING.value,
        }
        for task in tasks
    ):
        new_state = CooperationPipelineState.VERIFYING.value
    elif any(
        state in {CooperationTaskState.CLAIMED.value, CooperationTaskState.RUNNING.value}
        for state in states
    ):
        new_state = CooperationPipelineState.RUNNING.value
    elif any(state == CooperationTaskState.QUEUED.value for state in states):
        new_state = CooperationPipelineState.QUEUED.value
    elif any(
        task["state"] == CooperationTaskState.BLOCKED.value and task["requires_approval"]
        for task in tasks
    ) and not _approval_granted(db, pipeline_id):
        new_state = CooperationPipelineState.WAITING_FOR_APPROVAL.value
    else:
        new_state = CooperationPipelineState.CREATED.value

    if old_state != new_state or finished_at:
        db.execute(
            """UPDATE cooperation_pipeline_runs
               SET state=?,updated_at=?,finished_at=COALESCE(?,finished_at)
               WHERE id=?""",
            (new_state, _now(), finished_at, pipeline_id),
        )
        if old_state != new_state:
            _event(
                db,
                pipeline_id=pipeline_id,
                user_id=int(pipeline["user_id"]),
                event_type=f"pipeline.{new_state}",
                payload={"previous_state": old_state},
            )
    return new_state


def _task_blueprint(mode: PipelineMode) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = [
        {
            "key": "context",
            "name": "Resolve project and repository context",
            "capability": "context",
            "depends_on": [],
            "requires_approval": False,
        },
        {
            "key": "inspect",
            "name": "Inspect repository and runtime evidence",
            "capability": "repository-read",
            "depends_on": ["context"],
            "requires_approval": False,
        },
        {
            "key": "plan",
            "name": "Prepare an evidence-based execution plan",
            "capability": "planning",
            "depends_on": ["inspect"],
            "requires_approval": False,
        },
    ]
    if mode in {"build", "fix", "deploy"}:
        tasks.append(
            {
                "key": "implement",
                "name": "Implement the approved repository change",
                "capability": "repository-write",
                "depends_on": ["plan"],
                "requires_approval": True,
            }
        )
        tasks.extend(
            [
                {
                    "key": "test",
                    "name": "Run targeted and regression tests",
                    "capability": "testing",
                    "depends_on": ["implement"],
                    "requires_approval": False,
                },
                {
                    "key": "security",
                    "name": "Review security and policy boundaries",
                    "capability": "security",
                    "depends_on": ["test"],
                    "requires_approval": False,
                },
            ]
        )
    if mode == "deploy":
        tasks.append(
            {
                "key": "deploy",
                "name": "Deploy the verified artifact",
                "capability": "deployment",
                "depends_on": ["security"],
                "requires_approval": True,
            }
        )
    if mode == "monitor":
        tasks.append(
            {
                "key": "observe",
                "name": "Collect health, logs, metrics, and traces",
                "capability": "observability",
                "depends_on": ["plan"],
                "requires_approval": False,
            }
        )
    terminal_dependencies = [tasks[-1]["key"]]
    tasks.append(
        {
            "key": "verify",
            "name": "Verify evidence and publish the final result",
            "capability": "verification",
            "depends_on": terminal_dependencies,
            "requires_approval": False,
        }
    )
    return tasks


def _serialize_task(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "pipeline_id": row["pipeline_id"],
        "task_key": row["task_key"],
        "name": row["name"],
        "capability": row["capability"],
        "sequence": row["sequence"],
        "state": row["state"],
        "requires_approval": bool(row["requires_approval"]),
        "depends_on": _loads(row["depends_on_json"], []),
        "input": _loads(row["input_json"], {}),
        "output": _loads(row["output_json"], {}),
        "claimed_by_worker_id": row["claimed_by_worker_id"],
        "attempt": row["attempt"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "error_detail": row["error_detail"],
    }


def _serialize_worker(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "capabilities": _loads(row["capabilities_json"], []),
        "status": row["status"],
        "capacity": row["capacity"],
        "active_tasks": row["active_tasks"],
        "endpoint": row["endpoint"],
        "metadata": _loads(row["metadata_json"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_heartbeat": row["last_heartbeat"],
    }


def _serialize_pipeline(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    tasks = db.execute(
        "SELECT * FROM cooperation_tasks WHERE pipeline_id=? ORDER BY sequence",
        (row["id"],),
    ).fetchall()
    approvals = db.execute(
        "SELECT * FROM cooperation_approvals WHERE pipeline_id=? ORDER BY created_at",
        (row["id"],),
    ).fetchall()
    artifacts = db.execute(
        "SELECT * FROM cooperation_artifacts WHERE pipeline_id=? ORDER BY created_at",
        (row["id"],),
    ).fetchall()
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "repository_id": row["repository_id"],
        "project_id": row["project_id"],
        "objective": row["objective"],
        "mode": row["mode"],
        "environment": row["environment"],
        "branch": row["branch"],
        "state": row["state"],
        "allow_writes": bool(row["allow_writes"]),
        "repository_role": row["repository_role"],
        "metadata": _loads(row["metadata_json"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "error_detail": row["error_detail"],
        "tasks": [_serialize_task(task) for task in tasks],
        "approvals": [
            {
                "id": approval["id"],
                "action": approval["action"],
                "state": approval["state"],
                "reason": approval["reason"],
                "created_at": approval["created_at"],
                "decided_at": approval["decided_at"],
            }
            for approval in approvals
        ],
        "artifacts": [
            {
                "id": artifact["id"],
                "task_id": artifact["task_id"],
                "kind": artifact["kind"],
                "name": artifact["name"],
                "uri": artifact["uri"],
                "sha256": artifact["sha256"],
                "metadata": _loads(artifact["metadata_json"], {}),
                "created_at": artifact["created_at"],
            }
            for artifact in artifacts
        ],
    }


def _create_pipeline(
    body: CooperationPipelineCreate,
    user: sqlite3.Row,
    repository_role: str | None,
) -> dict[str, Any]:
    pipeline_id = f"pipe_{uuid.uuid4().hex}"
    now = _now()
    blueprint = _task_blueprint(body.mode)
    task_ids = {item["key"]: f"task_{uuid.uuid4().hex}" for item in blueprint}
    with _LOCK, _db() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """INSERT INTO cooperation_pipeline_runs(
                id,user_id,repository_id,project_id,objective,mode,environment,branch,
                state,allow_writes,repository_role,metadata_json,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                pipeline_id,
                int(user["id"]),
                body.repository_id,
                body.project_id,
                body.objective.strip(),
                body.mode,
                body.environment,
                body.branch,
                CooperationPipelineState.CREATED.value,
                int(body.allow_writes),
                repository_role,
                _json(body.metadata),
                now,
                now,
            ),
        )
        for sequence, item in enumerate(blueprint, start=1):
            dependencies = [task_ids[key] for key in item["depends_on"]]
            task_state = (
                CooperationTaskState.QUEUED.value
                if not dependencies and not item["requires_approval"]
                else CooperationTaskState.BLOCKED.value
            )
            db.execute(
                """INSERT INTO cooperation_tasks(
                    id,pipeline_id,user_id,task_key,name,capability,sequence,state,
                    requires_approval,depends_on_json,input_json,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task_ids[item["key"]],
                    pipeline_id,
                    int(user["id"]),
                    item["key"],
                    item["name"],
                    item["capability"],
                    sequence,
                    task_state,
                    int(item["requires_approval"]),
                    _json(dependencies),
                    _json(
                        {
                            "objective": body.objective.strip(),
                            "mode": body.mode,
                            "repository_id": body.repository_id,
                            "project_id": body.project_id,
                            "environment": body.environment,
                            "branch": body.branch,
                        }
                    ),
                    now,
                    now,
                ),
            )
        if any(item["requires_approval"] for item in blueprint):
            db.execute(
                """INSERT INTO cooperation_approvals(
                    id,pipeline_id,user_id,action,state,created_at
                ) VALUES (?,?,?,?,?,?)""",
                (
                    f"approval_{uuid.uuid4().hex}",
                    pipeline_id,
                    int(user["id"]),
                    "repository-write-and-deploy",
                    (
                        CooperationApprovalState.APPROVED.value
                        if body.allow_writes
                        else CooperationApprovalState.PENDING.value
                    ),
                    now,
                ),
            )
        _event(
            db,
            pipeline_id=pipeline_id,
            user_id=int(user["id"]),
            event_type="pipeline.created",
            payload={
                "mode": body.mode,
                "repository_id": body.repository_id,
                "task_count": len(blueprint),
            },
        )
        _refresh_pipeline_state(db, pipeline_id)
        db.commit()
        row = _pipeline_row(db, pipeline_id, int(user["id"]))
        return _serialize_pipeline(db, row)


@router.get("/modules")
def control_plane_modules() -> dict[str, Any]:
    """Return the truthful implementation state of the twenty control-plane modules."""
    return {
        "product": "Amosclaud Control Plane",
        "cooperation_contract": "durable-task-event-artifact-approval",
        "modules": list(CONTROL_PLANE_MODULES),
    }


@router.get("/overview")
def cooperation_overview(user: sqlite3.Row = Depends(_current_user)) -> dict[str, Any]:
    user_id = int(user["id"])
    with _db() as db:
        pipeline_counts = {
            row["state"]: row["count"]
            for row in db.execute(
                """SELECT state,COUNT(*) AS count FROM cooperation_pipeline_runs
                   WHERE user_id=? GROUP BY state""",
                (user_id,),
            ).fetchall()
        }
        task_counts = {
            row["state"]: row["count"]
            for row in db.execute(
                """SELECT state,COUNT(*) AS count FROM cooperation_tasks
                   WHERE user_id=? GROUP BY state""",
                (user_id,),
            ).fetchall()
        }
        worker_counts = {
            row["status"]: row["count"]
            for row in db.execute(
                """SELECT status,COUNT(*) AS count FROM cooperation_workers
                   WHERE user_id=? GROUP BY status""",
                (user_id,),
            ).fetchall()
        }
        pending_approvals = db.execute(
            """SELECT COUNT(*) FROM cooperation_approvals
               WHERE user_id=? AND state='pending'""",
            (user_id,),
        ).fetchone()[0]
    return {
        "pipeline_counts": pipeline_counts,
        "task_counts": task_counts,
        "worker_counts": worker_counts,
        "pending_approvals": pending_approvals,
        "modules": list(CONTROL_PLANE_MODULES),
    }


@router.post("/pipelines", status_code=201)
def create_cooperation_pipeline(
    body: CooperationPipelineCreate,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    repository_role: str | None = None
    if body.repository_id is not None:
        with repositories._db() as db:
            access = repositories._access(db, body.repository_id, int(user["id"]))
            repository_role = str(access["role"] or "viewer")
            if body.allow_writes and body.mode in {"build", "fix", "deploy"}:
                repositories._require_write(access)
    return _create_pipeline(body, user, repository_role)


@router.get("/pipelines")
def list_cooperation_pipelines(
    state: CooperationPipelineState | None = None,
    repository_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    clauses = ["user_id=?"]
    values: list[Any] = [int(user["id"])]
    if state is not None:
        clauses.append("state=?")
        values.append(state.value)
    if repository_id is not None:
        clauses.append("repository_id=?")
        values.append(repository_id)
    values.append(limit)
    with _db() as db:
        rows = db.execute(
            f"""SELECT * FROM cooperation_pipeline_runs
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC LIMIT ?""",
            tuple(values),
        ).fetchall()
        return {"items": [_serialize_pipeline(db, row) for row in rows]}


@router.get("/pipelines/{pipeline_id}")
def get_cooperation_pipeline(
    pipeline_id: str,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    with _db() as db:
        row = _pipeline_row(
            db, pipeline_id, int(user["id"]), administrator=_is_admin(user)
        )
        return _serialize_pipeline(db, row)


@router.get("/pipelines/{pipeline_id}/events")
def cooperation_pipeline_events(
    pipeline_id: str,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1_000),
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    with _db() as db:
        pipeline = _pipeline_row(
            db, pipeline_id, int(user["id"]), administrator=_is_admin(user)
        )
        rows = db.execute(
            """SELECT * FROM cooperation_events
               WHERE pipeline_id=? AND sequence>? ORDER BY sequence LIMIT ?""",
            (pipeline_id, after, limit),
        ).fetchall()
    return {
        "pipeline_id": pipeline["id"],
        "items": [
            {
                "sequence": row["sequence"],
                "task_id": row["task_id"],
                "event_type": row["event_type"],
                "payload": _loads(row["payload_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ],
    }


@router.post("/pipelines/{pipeline_id}/approve")
def approve_cooperation_pipeline(
    pipeline_id: str,
    body: CooperationApprovalDecision,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    user_id = int(user["id"])
    with _LOCK, _db() as db:
        db.execute("BEGIN IMMEDIATE")
        pipeline = _pipeline_row(
            db, pipeline_id, user_id, administrator=_is_admin(user)
        )
        if pipeline["repository_id"] is not None:
            with repositories._db() as repository_db:
                access = repositories._access(
                    repository_db, int(pipeline["repository_id"]), user_id
                )
                repositories._require_write(access)
        pending = db.execute(
            """SELECT id FROM cooperation_approvals
               WHERE pipeline_id=? AND state='pending' ORDER BY created_at LIMIT 1""",
            (pipeline_id,),
        ).fetchone()
        if not pending:
            raise HTTPException(status_code=409, detail="No pending approval exists")
        now = _now()
        db.execute(
            """UPDATE cooperation_approvals
               SET state='approved',reason=?,decided_at=? WHERE id=?""",
            (body.reason.strip(), now, pending["id"]),
        )
        db.execute(
            """UPDATE cooperation_pipeline_runs
               SET allow_writes=1,updated_at=? WHERE id=?""",
            (now, pipeline_id),
        )
        _event(
            db,
            pipeline_id=pipeline_id,
            user_id=user_id,
            event_type="approval.approved",
            payload={"approval_id": pending["id"], "reason": body.reason.strip()},
        )
        _release_ready_tasks(db, pipeline_id)
        _refresh_pipeline_state(db, pipeline_id)
        db.commit()
        return _serialize_pipeline(db, _pipeline_row(db, pipeline_id, user_id, administrator=True))


@router.post("/pipelines/{pipeline_id}/reject")
def reject_cooperation_pipeline(
    pipeline_id: str,
    body: CooperationApprovalDecision,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    user_id = int(user["id"])
    with _LOCK, _db() as db:
        db.execute("BEGIN IMMEDIATE")
        pipeline = _pipeline_row(
            db, pipeline_id, user_id, administrator=_is_admin(user)
        )
        now = _now()
        pending = db.execute(
            """SELECT id FROM cooperation_approvals
               WHERE pipeline_id=? AND state='pending' ORDER BY created_at LIMIT 1""",
            (pipeline_id,),
        ).fetchone()
        if not pending:
            raise HTTPException(status_code=409, detail="No pending approval exists")
        db.execute(
            """UPDATE cooperation_approvals
               SET state='rejected',reason=?,decided_at=? WHERE id=?""",
            (body.reason.strip(), now, pending["id"]),
        )
        db.execute(
            """UPDATE cooperation_tasks SET state='cancelled',updated_at=?,finished_at=?
               WHERE pipeline_id=? AND state IN ('blocked','queued')""",
            (now, now, pipeline_id),
        )
        db.execute(
            """UPDATE cooperation_pipeline_runs
               SET state='cancelled',updated_at=?,finished_at=? WHERE id=?""",
            (now, now, pipeline_id),
        )
        _event(
            db,
            pipeline_id=pipeline_id,
            user_id=int(pipeline["user_id"]),
            event_type="approval.rejected",
            payload={"approval_id": pending["id"], "reason": body.reason.strip()},
        )
        db.commit()
        return _serialize_pipeline(db, _pipeline_row(db, pipeline_id, user_id, administrator=True))


@router.post("/pipelines/{pipeline_id}/cancel", status_code=204, response_class=Response)
def cancel_cooperation_pipeline(
    pipeline_id: str,
    user: sqlite3.Row = Depends(_current_user),
) -> Response:
    user_id = int(user["id"])
    with _LOCK, _db() as db:
        db.execute("BEGIN IMMEDIATE")
        pipeline = _pipeline_row(
            db, pipeline_id, user_id, administrator=_is_admin(user)
        )
        if pipeline["state"] in {
            CooperationPipelineState.COMPLETED.value,
            CooperationPipelineState.FAILED.value,
            CooperationPipelineState.CANCELLED.value,
        }:
            raise HTTPException(status_code=409, detail="Pipeline already finished")
        now = _now()
        db.execute(
            """UPDATE cooperation_pipeline_runs
               SET state='cancelled',updated_at=?,finished_at=? WHERE id=?""",
            (now, now, pipeline_id),
        )
        db.execute(
            """UPDATE cooperation_tasks SET state='cancelled',updated_at=?,finished_at=?
               WHERE pipeline_id=? AND state NOT IN ('completed','failed','cancelled')""",
            (now, now, pipeline_id),
        )
        _event(
            db,
            pipeline_id=pipeline_id,
            user_id=int(pipeline["user_id"]),
            event_type="pipeline.cancelled",
        )
        db.commit()
    return Response(status_code=204)


@router.post("/workers", status_code=201)
def register_cooperation_worker(
    body: CooperationWorkerRegister,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    capabilities = sorted({item.strip() for item in body.capabilities if item.strip()})
    if not capabilities:
        raise HTTPException(status_code=422, detail="At least one capability is required")
    now = _now()
    worker_id = f"worker_{uuid.uuid4().hex}"
    with _LOCK, _db() as db:
        try:
            db.execute(
                """INSERT INTO cooperation_workers(
                    id,user_id,name,capabilities_json,status,capacity,active_tasks,
                    endpoint,metadata_json,created_at,updated_at,last_heartbeat
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    worker_id,
                    int(user["id"]),
                    body.name.strip(),
                    _json(capabilities),
                    "ready",
                    body.capacity,
                    0,
                    body.endpoint,
                    _json(body.metadata),
                    now,
                    now,
                    now,
                ),
            )
            db.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Worker name already exists") from exc
        row = db.execute(
            "SELECT * FROM cooperation_workers WHERE id=?", (worker_id,)
        ).fetchone()
    return _serialize_worker(row)


@router.get("/workers")
def list_cooperation_workers(
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    with _db() as db:
        rows = db.execute(
            """SELECT * FROM cooperation_workers
               WHERE user_id=? ORDER BY name""",
            (int(user["id"]),),
        ).fetchall()
    return {"items": [_serialize_worker(row) for row in rows]}


@router.post("/workers/{worker_id}/heartbeat")
def heartbeat_cooperation_worker(
    worker_id: str,
    body: CooperationWorkerHeartbeat,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    with _LOCK, _db() as db:
        row = db.execute(
            "SELECT * FROM cooperation_workers WHERE id=? AND user_id=?",
            (worker_id, int(user["id"])),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Worker not found")
        active_tasks = row["active_tasks"] if body.active_tasks is None else body.active_tasks
        metadata = {**_loads(row["metadata_json"], {}), **body.metadata}
        now = _now()
        db.execute(
            """UPDATE cooperation_workers
               SET status=?,active_tasks=?,metadata_json=?,updated_at=?,last_heartbeat=?
               WHERE id=?""",
            (body.status, active_tasks, _json(metadata), now, now, worker_id),
        )
        db.commit()
        updated = db.execute(
            "SELECT * FROM cooperation_workers WHERE id=?", (worker_id,)
        ).fetchone()
    return _serialize_worker(updated)


@router.post("/workers/{worker_id}/claim")
def claim_cooperation_task(
    worker_id: str,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    user_id = int(user["id"])
    with _LOCK, _db() as db:
        db.execute("BEGIN IMMEDIATE")
        worker = db.execute(
            "SELECT * FROM cooperation_workers WHERE id=? AND user_id=?",
            (worker_id, user_id),
        ).fetchone()
        if not worker:
            raise HTTPException(status_code=404, detail="Worker not found")
        if worker["status"] not in {"ready", "busy"}:
            raise HTTPException(status_code=409, detail="Worker is not accepting tasks")
        if int(worker["active_tasks"]) >= int(worker["capacity"]):
            raise HTTPException(status_code=409, detail="Worker is at capacity")
        capabilities = set(_loads(worker["capabilities_json"], []))
        candidates = db.execute(
            """SELECT t.* FROM cooperation_tasks t
               JOIN cooperation_pipeline_runs p ON p.id=t.pipeline_id
               WHERE t.user_id=? AND t.state='queued'
                 AND p.state NOT IN ('cancelled','failed','completed')
               ORDER BY p.created_at,t.sequence LIMIT 200""",
            (user_id,),
        ).fetchall()
        task = next(
            (
                candidate
                for candidate in candidates
                if candidate["capability"] in capabilities
                and _dependencies_complete(db, candidate)
            ),
            None,
        )
        if task is None:
            db.commit()
            return {"task": None}
        now = _now()
        db.execute(
            """UPDATE cooperation_tasks
               SET state='claimed',claimed_by_worker_id=?,attempt=attempt+1,
                   started_at=COALESCE(started_at,?),updated_at=?
               WHERE id=? AND state='queued'""",
            (worker_id, now, now, task["id"]),
        )
        db.execute(
            """UPDATE cooperation_workers
               SET active_tasks=active_tasks+1,
                   status=CASE WHEN active_tasks+1>=capacity THEN 'busy' ELSE status END,
                   updated_at=? WHERE id=?""",
            (now, worker_id),
        )
        db.execute(
            """UPDATE cooperation_pipeline_runs
               SET state='running',started_at=COALESCE(started_at,?),updated_at=?
               WHERE id=?""",
            (now, now, task["pipeline_id"]),
        )
        _event(
            db,
            pipeline_id=task["pipeline_id"],
            task_id=task["id"],
            user_id=user_id,
            event_type="task.claimed",
            payload={"worker_id": worker_id, "capability": task["capability"]},
        )
        db.commit()
        claimed = _task_row(db, task["id"], user_id)
        return {"task": _serialize_task(claimed)}


def _store_artifacts(
    db: sqlite3.Connection,
    *,
    pipeline_id: str,
    task_id: str,
    user_id: int,
    artifacts: list[dict[str, Any]],
) -> None:
    now = _now()
    for artifact in artifacts:
        name = str(artifact.get("name") or "artifact")[:500]
        kind = str(artifact.get("kind") or "evidence")[:100]
        uri = str(artifact.get("uri") or "")[:4_000]
        if not uri:
            continue
        db.execute(
            """INSERT INTO cooperation_artifacts(
                id,pipeline_id,task_id,user_id,kind,name,uri,sha256,metadata_json,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                f"artifact_{uuid.uuid4().hex}",
                pipeline_id,
                task_id,
                user_id,
                kind,
                name,
                uri,
                str(artifact.get("sha256") or "")[:200] or None,
                _json(artifact.get("metadata") or {}),
                now,
            ),
        )


@router.post("/tasks/{task_id}/complete")
def complete_cooperation_task(
    task_id: str,
    body: CooperationTaskResult,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    user_id = int(user["id"])
    with _LOCK, _db() as db:
        db.execute("BEGIN IMMEDIATE")
        task = _task_row(db, task_id, user_id, administrator=_is_admin(user))
        if task["state"] not in {
            CooperationTaskState.CLAIMED.value,
            CooperationTaskState.RUNNING.value,
        }:
            raise HTTPException(status_code=409, detail="Task is not active")
        claimed_worker = task["claimed_by_worker_id"]
        if body.worker_id and claimed_worker and body.worker_id != claimed_worker:
            raise HTTPException(status_code=403, detail="Task belongs to another worker")
        now = _now()
        output = {**body.output, "summary": body.summary.strip()}
        db.execute(
            """UPDATE cooperation_tasks
               SET state='completed',output_json=?,updated_at=?,finished_at=?,error_detail=''
               WHERE id=?""",
            (_json(output), now, now, task_id),
        )
        if claimed_worker:
            db.execute(
                """UPDATE cooperation_workers
                   SET active_tasks=MAX(active_tasks-1,0),
                       status=CASE WHEN status='busy' THEN 'ready' ELSE status END,
                       updated_at=? WHERE id=?""",
                (now, claimed_worker),
            )
        _store_artifacts(
            db,
            pipeline_id=task["pipeline_id"],
            task_id=task_id,
            user_id=int(task["user_id"]),
            artifacts=body.artifacts,
        )
        _event(
            db,
            pipeline_id=task["pipeline_id"],
            task_id=task_id,
            user_id=int(task["user_id"]),
            event_type="task.completed",
            payload={"worker_id": claimed_worker, "summary": body.summary.strip()},
        )
        _release_ready_tasks(db, task["pipeline_id"])
        _refresh_pipeline_state(db, task["pipeline_id"])
        db.commit()
        pipeline = _pipeline_row(db, task["pipeline_id"], user_id, administrator=True)
        return _serialize_pipeline(db, pipeline)


@router.post("/tasks/{task_id}/fail")
def fail_cooperation_task(
    task_id: str,
    body: CooperationTaskFailure,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    user_id = int(user["id"])
    with _LOCK, _db() as db:
        db.execute("BEGIN IMMEDIATE")
        task = _task_row(db, task_id, user_id, administrator=_is_admin(user))
        if task["state"] not in {
            CooperationTaskState.CLAIMED.value,
            CooperationTaskState.RUNNING.value,
        }:
            raise HTTPException(status_code=409, detail="Task is not active")
        claimed_worker = task["claimed_by_worker_id"]
        if body.worker_id and claimed_worker and body.worker_id != claimed_worker:
            raise HTTPException(status_code=403, detail="Task belongs to another worker")
        now = _now()
        next_state = (
            CooperationTaskState.QUEUED.value
            if body.retryable and int(task["attempt"]) < 3
            else CooperationTaskState.FAILED.value
        )
        db.execute(
            """UPDATE cooperation_tasks
               SET state=?,claimed_by_worker_id=NULL,updated_at=?,
                   finished_at=CASE WHEN ?='failed' THEN ? ELSE NULL END,error_detail=?
               WHERE id=?""",
            (next_state, now, next_state, now, body.error.strip(), task_id),
        )
        if claimed_worker:
            db.execute(
                """UPDATE cooperation_workers
                   SET active_tasks=MAX(active_tasks-1,0),
                       status=CASE WHEN status='busy' THEN 'ready' ELSE status END,
                       updated_at=? WHERE id=?""",
                (now, claimed_worker),
            )
        _event(
            db,
            pipeline_id=task["pipeline_id"],
            task_id=task_id,
            user_id=int(task["user_id"]),
            event_type="task.retry_queued" if body.retryable else "task.failed",
            payload={"worker_id": claimed_worker, "error": body.error.strip()},
        )
        _refresh_pipeline_state(db, task["pipeline_id"])
        db.commit()
        pipeline = _pipeline_row(db, task["pipeline_id"], user_id, administrator=True)
        return _serialize_pipeline(db, pipeline)
