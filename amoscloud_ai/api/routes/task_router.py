"""Global task routing for Amosclaud cloud and self-hosted runners."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Cookie, Header, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.agent_tokens import credit_tokens, debit_tokens
from amoscloud_ai.api.routes.auth import _connect, get_user_from_session
from amoscloud_ai.api.routes.provider_api import _authenticate as authenticate_api_key
from amoscloud_ai.api.routes.operation_buckets import ensure_bucket_schema, ensure_user_bucket

router = APIRouter(tags=["global-task-router"])

TaskMode = Literal["ask", "build", "fix", "test", "review", "deploy", "monitor"]
TaskDelivery = Literal["report", "patch", "pull_request"]
ExecutionTarget = Literal["auto", "cloud", "self_hosted", "github"]
TaskStatus = Literal[
    "queued", "awaiting_approval", "running", "completed", "failed", "cancelled"
]


class TaskCreate(BaseModel):
    objective: str = Field(min_length=3, max_length=20_000)
    repository: str | None = Field(default=None, max_length=300)
    mode: TaskMode = "build"
    delivery: TaskDelivery = "pull_request"
    runner_id: str | None = Field(default=None, max_length=64)
    execution_target: ExecutionTarget = "auto"
    require_approval: bool = True
    metadata: dict = Field(default_factory=dict)


class RunnerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    capabilities: list[str] = Field(
        default_factory=lambda: ["ask", "build", "test", "review"], max_length=30
    )
    labels: list[str] = Field(default_factory=list, max_length=30)


class RunnerHeartbeat(BaseModel):
    version: str = Field(default="unknown", max_length=50)
    capabilities: list[str] = Field(default_factory=list, max_length=30)
    system: dict = Field(default_factory=dict)


class TaskCompletion(BaseModel):
    status: Literal["completed", "failed"]
    summary: str = Field(min_length=1, max_length=20_000)
    evidence: list[str] = Field(default_factory=list, max_length=200)
    artifacts: list[dict] = Field(default_factory=list, max_length=100)
    pull_request_url: str | None = Field(default=None, max_length=500)
    verification_id: str | None = Field(default=None, min_length=8, max_length=200)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _ensure_schema(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS task_runners (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            token_prefix TEXT NOT NULL,
            capabilities_json TEXT NOT NULL,
            labels_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'offline',
            version TEXT,
            system_json TEXT,
            created_at TEXT NOT NULL,
            last_seen_at TEXT,
            revoked_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS global_tasks (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            repository TEXT,
            objective TEXT NOT NULL,
            mode TEXT NOT NULL,
            delivery TEXT NOT NULL,
            status TEXT NOT NULL,
            execution_target TEXT NOT NULL DEFAULT 'auto',
            runner_id TEXT,
            require_approval INTEGER NOT NULL DEFAULT 1,
            reserved_credits INTEGER NOT NULL,
            metadata_json TEXT NOT NULL,
            summary TEXT,
            pull_request_url TEXT,
            artifacts_json TEXT,
            created_at TEXT NOT NULL,
            approved_at TEXT,
            started_at TEXT,
            finished_at TEXT,
            cancelled_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(runner_id) REFERENCES task_runners(id)
        );
        CREATE TABLE IF NOT EXISTS global_task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(task_id) REFERENCES global_tasks(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_global_tasks_owner_created
            ON global_tasks(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_global_tasks_status_created
            ON global_tasks(status, created_at);
        """)
    columns = {
        row[1] for row in db.execute("PRAGMA table_info(global_tasks)").fetchall()
    }
    if "execution_target" not in columns:
        db.execute(
            "ALTER TABLE global_tasks ADD COLUMN execution_target TEXT NOT NULL DEFAULT 'auto'"
        )
    ensure_bucket_schema(db)
    db.commit()


def _json(value) -> str:
    import json

    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _loads(value: str | None, fallback):
    import json

    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _actor(
    amos_session: str | None,
    authorization: str | None,
) -> int:
    user = get_user_from_session(amos_session)
    if user:
        return int(user["id"])
    if authorization:
        credential = authenticate_api_key(authorization)
        return int(credential["user_id"])
    raise HTTPException(status_code=401, detail="Amosclaud account or API key required")


def _task_cost(body: TaskCreate) -> int:
    base = {"ask": 1, "test": 3, "review": 4, "build": 5, "fix": 5, "monitor": 2, "deploy": 6}[
        body.mode
    ]
    context = min(5, len(body.objective) // 2_000)
    return base + context


def _event(
    db: sqlite3.Connection, task_id: str, event_type: str, message: str, details=None
) -> None:
    db.execute(
        """INSERT INTO global_task_events(task_id,event_type,message,details_json,created_at)
           VALUES (?,?,?,?,?)""",
        (task_id, event_type, message, _json(details or {}), _now()),
    )


def _task_dict(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["require_approval"] = bool(item["require_approval"])
    item["metadata"] = _loads(item.pop("metadata_json"), {})
    item["artifacts"] = _loads(item.pop("artifacts_json"), [])
    return item


def _owned_task(db: sqlite3.Connection, task_id: str, user_id: int) -> sqlite3.Row:
    row = db.execute(
        "SELECT * FROM global_tasks WHERE id=? AND user_id=?", (task_id, user_id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return row


def _runner_auth(
    db: sqlite3.Connection, runner_id: str, authorization: str | None
) -> sqlite3.Row:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Runner credential required")
    raw = authorization.removeprefix("Bearer ").strip()
    row = db.execute(
        """SELECT * FROM task_runners
           WHERE id=? AND token_hash=? AND revoked_at IS NULL""",
        (runner_id, _hash(raw)),
    ).fetchone()
    if not row:
        raise HTTPException(
            status_code=401, detail="Runner credential is invalid or revoked"
        )
    return row


@router.post("/tasks", status_code=202)
def create_task(
    body: TaskCreate,
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    user_id = _actor(amos_session, authorization)
    task_id = "task_" + uuid.uuid4().hex
    cost = _task_cost(body)
    execution_target = body.execution_target
    if execution_target == "auto":
        execution_target = (
            "self_hosted"
            if body.runner_id
            else ("github" if body.repository else "cloud")
        )
    if execution_target == "self_hosted" and not body.runner_id:
        raise HTTPException(
            status_code=422, detail="Select a private runner for self-hosted execution"
        )
    if execution_target == "github" and not body.repository:
        raise HTTPException(
            status_code=422, detail="Select a connected GitHub repository"
        )

    with _connect() as db:
        _ensure_schema(db)
        if body.runner_id:
            runner = db.execute(
                "SELECT id FROM task_runners WHERE id=? AND user_id=? AND revoked_at IS NULL",
                (body.runner_id, user_id),
            ).fetchone()
            if not runner:
                raise HTTPException(status_code=404, detail="Runner not found")
        if not debit_tokens(db, user_id, cost, reference=task_id):
            raise HTTPException(
                status_code=402,
                detail={"code": "agent_tokens_required", "purchase_url": "/api-access"},
            )
        status = "awaiting_approval" if body.require_approval else "queued"
        bucket = ensure_user_bucket(db, user_id, commit=False)
        db.execute(
            """INSERT INTO global_tasks
               (id,user_id,bucket_id,repository,objective,mode,delivery,status,execution_target,runner_id,
                require_approval,reserved_credits,metadata_json,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task_id,
                user_id,
                bucket["id"],
                body.repository,
                body.objective.strip(),
                body.mode,
                body.delivery,
                status,
                execution_target,
                body.runner_id,
                int(body.require_approval),
                cost,
                _json(body.metadata),
                _now(),
            ),
        )
        _event(
            db,
            task_id,
            "task.created",
            f"Task accepted in {status} state.",
            {"credits_reserved": cost, "bucket_id": bucket["id"]},
        )
        db.commit()
        row = db.execute("SELECT * FROM global_tasks WHERE id=?", (task_id,)).fetchone()
    from amoscloud_ai.api.routes.webhooks import dispatch_webhook_event

    dispatch_webhook_event(
        user_id,
        "task.created",
        {
            "task_id": task_id,
            "bucket_id": bucket["id"],
            "status": status,
            "repository": body.repository,
            "mode": body.mode,
            "execution_target": execution_target,
        },
    )
    if status == "queued" and execution_target in {"cloud", "github"}:
        from amoscloud_ai.cloud_task_runner import dispatch_cloud_task

        dispatch_cloud_task(task_id)
    return _task_dict(row)


@router.get("/tasks")
def list_tasks(
    limit: int = 50,
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> list[dict]:
    user_id = _actor(amos_session, authorization)
    safe_limit = max(1, min(limit, 200))
    with _connect() as db:
        _ensure_schema(db)
        rows = db.execute(
            "SELECT * FROM global_tasks WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, safe_limit),
        ).fetchall()
    return [_task_dict(row) for row in rows]


@router.get("/tasks/{task_id}")
def get_task(
    task_id: str,
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    user_id = _actor(amos_session, authorization)
    with _connect() as db:
        _ensure_schema(db)
        return _task_dict(_owned_task(db, task_id, user_id))


@router.get("/tasks/{task_id}/logs")
def task_logs(
    task_id: str,
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> list[dict]:
    user_id = _actor(amos_session, authorization)
    with _connect() as db:
        _ensure_schema(db)
        _owned_task(db, task_id, user_id)
        rows = db.execute(
            """SELECT event_type,message,details_json,created_at
               FROM global_task_events WHERE task_id=? ORDER BY id""",
            (task_id,),
        ).fetchall()
    return [
        {
            "event_type": row["event_type"],
            "message": row["message"],
            "details": _loads(row["details_json"], {}),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


@router.post("/tasks/{task_id}/approve")
def approve_task(
    task_id: str,
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    user_id = _actor(amos_session, authorization)
    with _connect() as db:
        _ensure_schema(db)
        row = _owned_task(db, task_id, user_id)
        if row["status"] != "awaiting_approval":
            raise HTTPException(status_code=409, detail="Task is not awaiting approval")
        db.execute(
            "UPDATE global_tasks SET status='queued',approved_at=? WHERE id=?",
            (_now(), task_id),
        )
        _event(db, task_id, "task.approved", "Task approved and queued.")
        db.commit()
        row = db.execute("SELECT * FROM global_tasks WHERE id=?", (task_id,)).fetchone()
    if row["execution_target"] in {"cloud", "github"}:
        from amoscloud_ai.cloud_task_runner import dispatch_cloud_task

        dispatch_cloud_task(task_id)
    return _task_dict(row)


@router.post("/tasks/{task_id}/cancel")
def cancel_task(
    task_id: str,
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    user_id = _actor(amos_session, authorization)
    with _connect() as db:
        _ensure_schema(db)
        row = _owned_task(db, task_id, user_id)
        if row["status"] not in {"queued", "awaiting_approval"}:
            raise HTTPException(
                status_code=409, detail="Only unstarted tasks can be cancelled"
            )
        db.execute(
            "UPDATE global_tasks SET status='cancelled',cancelled_at=? WHERE id=?",
            (_now(), task_id),
        )
        credit_tokens(
            db,
            user_id,
            int(row["reserved_credits"]),
            reason="task_cancel_refund",
            reference=task_id,
        )
        _event(
            db,
            task_id,
            "task.cancelled",
            "Task cancelled and reserved credits refunded.",
        )
        db.commit()
        row = db.execute("SELECT * FROM global_tasks WHERE id=?", (task_id,)).fetchone()
    from amoscloud_ai.api.routes.webhooks import dispatch_webhook_event

    dispatch_webhook_event(
        user_id,
        "task.cancelled",
        {
            "task_id": task_id,
            "bucket_id": row["bucket_id"],
            "status": "cancelled",
            "summary": "Task cancelled.",
        },
    )
    return _task_dict(row)


@router.post("/runners", status_code=201)
def register_runner(
    body: RunnerCreate,
    amos_session: str | None = Cookie(default=None),
) -> dict:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(
            status_code=401, detail="Sign in to register a private runner"
        )
    runner_id = "runner_" + uuid.uuid4().hex
    raw_token = "amos_runner_" + secrets.token_urlsafe(36)
    with _connect() as db:
        _ensure_schema(db)
        db.execute(
            """INSERT INTO task_runners
               (id,user_id,name,token_hash,token_prefix,capabilities_json,labels_json,status,created_at)
               VALUES (?,?,?,?,?,?,?,'offline',?)""",
            (
                runner_id,
                user["id"],
                body.name.strip(),
                _hash(raw_token),
                raw_token[:20],
                _json(sorted(set(body.capabilities))),
                _json(sorted(set(body.labels))),
                _now(),
            ),
        )
        db.commit()
    return {
        "id": runner_id,
        "name": body.name.strip(),
        "runner_token": raw_token,
        "warning": "Copy this runner credential now. Amosclaud stores only its hash.",
    }


@router.get("/runners")
def list_runners(amos_session: str | None = Cookie(default=None)) -> list[dict]:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to view private runners")
    with _connect() as db:
        _ensure_schema(db)
        rows = db.execute(
            """SELECT id,name,token_prefix,capabilities_json,labels_json,status,version,
                      created_at,last_seen_at,revoked_at
               FROM task_runners WHERE user_id=? ORDER BY created_at DESC""",
            (user["id"],),
        ).fetchall()
    return [
        {
            **{
                key: value
                for key, value in dict(row).items()
                if key not in {"capabilities_json", "labels_json"}
            },
            "capabilities": _loads(row["capabilities_json"], []),
            "labels": _loads(row["labels_json"], []),
        }
        for row in rows
    ]


@router.post("/runners/{runner_id}/heartbeat")
def runner_heartbeat(
    runner_id: str,
    body: RunnerHeartbeat,
    authorization: str | None = Header(default=None),
) -> dict:
    with _connect() as db:
        _ensure_schema(db)
        runner = _runner_auth(db, runner_id, authorization)
        capabilities = body.capabilities or _loads(runner["capabilities_json"], [])
        db.execute(
            """UPDATE task_runners
               SET status='online',version=?,capabilities_json=?,system_json=?,last_seen_at=?
               WHERE id=?""",
            (body.version, _json(capabilities), _json(body.system), _now(), runner_id),
        )
        db.commit()
    return {"ok": True, "runner_id": runner_id}


@router.post("/runners/{runner_id}/claim")
def claim_task(
    runner_id: str,
    authorization: str | None = Header(default=None),
) -> dict | None:
    with _connect() as db:
        _ensure_schema(db)
        runner = _runner_auth(db, runner_id, authorization)
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            """SELECT * FROM global_tasks
               WHERE user_id=? AND status='queued' AND execution_target='self_hosted'
                 AND (runner_id IS NULL OR runner_id=?)
               ORDER BY created_at LIMIT 1""",
            (runner["user_id"], runner_id),
        ).fetchone()
        if not row:
            db.execute(
                "UPDATE task_runners SET status='online',last_seen_at=? WHERE id=?",
                (_now(), runner_id),
            )
            db.commit()
            return None
        cursor = db.execute(
            """UPDATE global_tasks SET status='running',runner_id=?,started_at=?
               WHERE id=? AND status='queued'""",
            (runner_id, _now(), row["id"]),
        )
        if cursor.rowcount != 1:
            db.rollback()
            return None
        _event(db, row["id"], "task.claimed", f"Claimed by runner {runner_id}.")
        db.execute(
            "UPDATE task_runners SET status='busy',last_seen_at=? WHERE id=?",
            (_now(), runner_id),
        )
        db.commit()
        row = db.execute(
            "SELECT * FROM global_tasks WHERE id=?", (row["id"],)
        ).fetchone()
    return _task_dict(row)


@router.post("/runners/{runner_id}/tasks/{task_id}/complete")
def complete_task(
    runner_id: str,
    task_id: str,
    body: TaskCompletion,
    authorization: str | None = Header(default=None),
) -> dict:
    if body.status == "completed" and (
        not body.verification_id or not body.evidence
    ):
        raise HTTPException(
            status_code=422,
            detail="Completed tasks require a verification_id and evidence",
        )
    with _connect() as db:
        _ensure_schema(db)
        runner = _runner_auth(db, runner_id, authorization)
        row = db.execute(
            """SELECT * FROM global_tasks
               WHERE id=? AND runner_id=? AND user_id=?""",
            (task_id, runner_id, runner["user_id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Claimed task not found")
        if row["status"] != "running":
            raise HTTPException(status_code=409, detail="Task is not running")
        db.execute(
            """UPDATE global_tasks
               SET status=?,summary=?,artifacts_json=?,pull_request_url=?,
                   verification_id=?,finished_at=?
               WHERE id=?""",
            (
                body.status,
                body.summary.strip(),
                _json(body.artifacts),
                body.pull_request_url,
                body.verification_id,
                _now(),
                task_id,
            ),
        )
        if body.status == "failed":
            credit_tokens(
                db,
                int(row["user_id"]),
                int(row["reserved_credits"]),
                reason="task_failure_refund",
                reference=task_id,
            )
        _event(
            db,
            task_id,
            f"task.{body.status}",
            body.summary.strip(),
            {
                "evidence": body.evidence,
                "artifacts": body.artifacts,
                "verification_id": body.verification_id,
            },
        )
        db.execute(
            "UPDATE task_runners SET status='online',last_seen_at=? WHERE id=?",
            (_now(), runner_id),
        )
        db.commit()
        updated = db.execute(
            "SELECT * FROM global_tasks WHERE id=?", (task_id,)
        ).fetchone()
    from amoscloud_ai.api.routes.webhooks import dispatch_webhook_event

    dispatch_webhook_event(
        int(row["user_id"]),
        f"task.{body.status}",
        {
            "task_id": task_id,
            "status": body.status,
            "summary": body.summary.strip(),
            "artifacts": body.artifacts,
            "pull_request_url": body.pull_request_url,
            "verification_id": body.verification_id,
            "bucket_id": row["bucket_id"],
        },
    )
    return _task_dict(updated)
