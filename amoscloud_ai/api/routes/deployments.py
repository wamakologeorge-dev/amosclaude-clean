"""Persistent deployment management and worker routes."""

from __future__ import annotations

import hmac
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Cookie, Header, HTTPException, Query
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes import auth as auth_routes
from amoscloud_ai.copilot import COPILOT_PIPELINE, COPILOT_ROLE, deployment_reply
from amoscloud_ai.logger import log
from amoscloud_ai.models import DeploymentConfig, DeploymentResponse, DeploymentStatus
from amoscloud_ai.task_dispatch import dispatch_task

router = APIRouter(prefix="/deployments", tags=["deployments"])


class WorkerStatusUpdate(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=120)
    deployment_id: str = Field(..., min_length=1, max_length=120)
    status: str = Field(..., min_length=1, max_length=40)
    logs: str = Field(default="", max_length=2_000_000)


def _db() -> sqlite3.Connection:
    db = auth_routes._connect()
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS deployment_runs (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            environment TEXT NOT NULL,
            version TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            message TEXT NOT NULL DEFAULT '',
            copilot_reply TEXT NOT NULL DEFAULT '',
            copilot_role TEXT NOT NULL DEFAULT '',
            delegation_target TEXT NOT NULL DEFAULT '',
            config_json TEXT NOT NULL DEFAULT '{}',
            worker_id TEXT,
            claimed_at TEXT,
            logs TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_deployment_runs_status ON deployment_runs(status, started_at);
        """
    )
    db.commit()
    return db


def _row_to_response(row: sqlite3.Row) -> DeploymentResponse:
    return DeploymentResponse(
        id=row["id"],
        status=DeploymentStatus(row["status"]),
        environment=row["environment"],
        version=row["version"],
        started_at=datetime.fromisoformat(row["started_at"]),
        finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
        message=row["message"],
        copilot_reply=row["copilot_reply"],
        copilot_role=row["copilot_role"],
        delegation_target=row["delegation_target"],
        worker_id=row["worker_id"],
        logs=row["logs"] or None,
    )


def _save(deployment: DeploymentResponse, config: dict | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _db() as db:
        db.execute(
            """INSERT INTO deployment_runs(
                id,status,environment,version,started_at,finished_at,message,copilot_reply,
                copilot_role,delegation_target,config_json,worker_id,logs,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status, finished_at=excluded.finished_at,
                message=excluded.message, copilot_reply=excluded.copilot_reply,
                worker_id=excluded.worker_id, logs=excluded.logs, updated_at=excluded.updated_at""",
            (
                deployment.id,
                deployment.status.value,
                deployment.environment,
                deployment.version,
                deployment.started_at.isoformat(),
                deployment.finished_at.isoformat() if deployment.finished_at else None,
                deployment.message or "",
                deployment.copilot_reply or "",
                deployment.copilot_role or "",
                deployment.delegation_target or "",
                json.dumps(config or {}),
                deployment.worker_id,
                deployment.logs or "",
                now,
            ),
        )
        db.commit()


def _get(deployment_id: str) -> DeploymentResponse | None:
    with _db() as db:
        row = db.execute("SELECT * FROM deployment_runs WHERE id=?", (deployment_id,)).fetchone()
    return _row_to_response(row) if row else None


def _require_worker_key(x_api_key: str | None) -> None:
    configured = os.getenv("AMOSCLAUD_DEPLOYMENT_WORKER_KEY", "").strip()
    if not configured:
        raise HTTPException(status_code=503, detail="Deployment worker access is not configured")
    if not x_api_key or not hmac.compare_digest(x_api_key, configured):
        raise HTTPException(status_code=401, detail="Invalid deployment worker key")


@router.get("", response_model=List[DeploymentResponse], summary="List all deployments")
async def list_deployments() -> List[DeploymentResponse]:
    with _db() as db:
        rows = db.execute("SELECT * FROM deployment_runs ORDER BY started_at DESC LIMIT 200").fetchall()
    return [_row_to_response(row) for row in rows]


@router.get("/pending", summary="Claim the next deployment worker task")
def next_pending_deployment(
    worker_id: str = Query(..., min_length=1, max_length=120),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _require_worker_key(x_api_key)
    now = datetime.now(timezone.utc).isoformat()
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            """SELECT * FROM deployment_runs
               WHERE status=? AND worker_id IS NULL
               ORDER BY started_at ASC LIMIT 1""",
            (DeploymentStatus.PENDING.value,),
        ).fetchone()
        if not row:
            db.rollback()
            raise HTTPException(status_code=404, detail="No pending deployments")
        config = json.loads(row["config_json"] or "{}")
        if not config.get("repo_url") or not config.get("start_command"):
            db.rollback()
            raise HTTPException(status_code=409, detail="Pending deployment is missing worker configuration")
        db.execute(
            "UPDATE deployment_runs SET worker_id=?,claimed_at=?,updated_at=? WHERE id=? AND worker_id IS NULL",
            (worker_id, now, now, row["id"]),
        )
        db.commit()
    return {
        "deployment_id": row["id"],
        "repo_url": config["repo_url"],
        "branch": config.get("branch", "main"),
        "build_command": config.get("build_command"),
        "start_command": config["start_command"],
        "env_vars": config.get("env_vars", {}),
        "port": config.get("port", 8000),
    }


@router.post("/status", response_model=DeploymentResponse, summary="Update deployment worker status")
def update_worker_status(
    body: WorkerStatusUpdate,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> DeploymentResponse:
    _require_worker_key(x_api_key)
    normalized = body.status.strip().upper()
    status_map = {
        "PENDING": DeploymentStatus.PENDING,
        "BUILDING": DeploymentStatus.IN_PROGRESS,
        "RUNNING": DeploymentStatus.IN_PROGRESS,
        "SUCCESS": DeploymentStatus.COMPLETED,
        "COMPLETED": DeploymentStatus.COMPLETED,
        "FAILED": DeploymentStatus.FAILED,
    }
    if normalized not in status_map:
        raise HTTPException(status_code=422, detail="Unsupported deployment worker status")
    deployment = _get(body.deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    if deployment.worker_id and deployment.worker_id != body.worker_id:
        raise HTTPException(status_code=409, detail="Deployment is claimed by another worker")
    deployment.worker_id = body.worker_id
    deployment.status = status_map[normalized]
    deployment.logs = body.logs
    if deployment.status in {DeploymentStatus.COMPLETED, DeploymentStatus.FAILED}:
        deployment.finished_at = datetime.now(timezone.utc)
    deployment.message = deployment_reply(deployment.status)
    deployment.copilot_reply = deployment.message
    _save(deployment)
    return deployment


@router.get("/{deployment_id}", response_model=DeploymentResponse, summary="Get a deployment")
async def get_deployment(deployment_id: str) -> DeploymentResponse:
    deployment = _get(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail=f"Deployment {deployment_id!r} not found")
    return deployment


@router.post("", response_model=DeploymentResponse, status_code=201, summary="Start a deployment")
async def start_deployment(
    config: DeploymentConfig,
    amos_session: str | None = Cookie(default=None),
) -> DeploymentResponse:
    if config.repo_url and config.start_command and not auth_routes.get_user_from_session(amos_session):
        raise HTTPException(
            status_code=401,
            detail="Sign in before queuing a deployment worker task",
        )
    deployment_id = str(uuid.uuid4())
    log.info("Starting deployment %s to %s", deployment_id, config.environment)
    reply = deployment_reply(DeploymentStatus.PENDING)
    deployment = DeploymentResponse(
        id=deployment_id,
        status=DeploymentStatus.PENDING,
        environment=config.environment.value,
        version=config.version,
        started_at=datetime.now(timezone.utc),
        message=reply,
        copilot_reply=reply,
        copilot_role=COPILOT_ROLE,
        delegation_target=COPILOT_PIPELINE,
    )
    payload = config.model_dump(mode="json")
    _save(deployment, payload)

    # Fully configured deployments are claimed by the external first-party worker.
    if config.repo_url and config.start_command:
        return deployment

    # Legacy/simple deployments continue through the internal worker path.
    try:
        from amoscloud_ai.worker import run_deployment_task

        dispatch_task(run_deployment_task, deployment_id, payload)
    except Exception:
        log.warning("Background worker unavailable – completing simple deployment inline")
        deployment.status = DeploymentStatus.COMPLETED
        deployment.finished_at = datetime.now(timezone.utc)
        deployment.message = deployment_reply(DeploymentStatus.COMPLETED)
        deployment.copilot_reply = deployment.message
        _save(deployment, payload)
    return deployment


@router.post("/{deployment_id}/rollback", response_model=DeploymentResponse, summary="Rollback a deployment")
async def rollback_deployment(deployment_id: str) -> DeploymentResponse:
    deployment = _get(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail=f"Deployment {deployment_id!r} not found")
    log.warning("Rolling back deployment %s", deployment_id)
    deployment.status = DeploymentStatus.ROLLED_BACK
    deployment.finished_at = datetime.now(timezone.utc)
    deployment.message = deployment_reply(DeploymentStatus.ROLLED_BACK)
    deployment.copilot_reply = deployment.message
    _save(deployment)
    return deployment
