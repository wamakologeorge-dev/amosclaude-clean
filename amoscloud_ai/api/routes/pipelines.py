"""Persistent pipeline management routes."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, HTTPException

from amoscloud_ai.api.routes.auth import DB_PATH
from amoscloud_ai.copilot import COPILOT_PIPELINE, COPILOT_ROLE, pipeline_reply
from amoscloud_ai.logger import log
from amoscloud_ai.models import PipelineJob, PipelineResponse, PipelineStatus, PipelineTrigger

router = APIRouter(prefix="/pipelines", tags=["pipelines"])
_LOCK = threading.RLock()


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            trigger TEXT NOT NULL,
            branch TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            message TEXT NOT NULL DEFAULT '',
            copilot_reply TEXT NOT NULL DEFAULT '',
            copilot_role TEXT NOT NULL DEFAULT '',
            delegation_target TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            jobs_json TEXT NOT NULL DEFAULT '[]',
            error_detail TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started ON pipeline_runs(started_at DESC);
        """
    )
    db.commit()
    return db


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    raise TypeError(type(value).__name__)


def _save(pipeline: PipelineResponse, payload: dict | None = None, error_detail: str = "") -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _LOCK, _db() as db:
        db.execute(
            """INSERT INTO pipeline_runs(
                id,status,trigger,branch,started_at,finished_at,message,copilot_reply,
                copilot_role,delegation_target,payload_json,jobs_json,error_detail,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status, finished_at=excluded.finished_at,
                message=excluded.message, copilot_reply=excluded.copilot_reply,
                jobs_json=excluded.jobs_json, error_detail=excluded.error_detail,
                updated_at=excluded.updated_at""",
            (
                pipeline.id,
                pipeline.status.value,
                pipeline.trigger,
                pipeline.branch,
                pipeline.started_at.isoformat(),
                pipeline.finished_at.isoformat() if pipeline.finished_at else None,
                pipeline.message or "",
                pipeline.copilot_reply or "",
                pipeline.copilot_role or "",
                pipeline.delegation_target or "",
                json.dumps(payload or {}, default=_json_default),
                json.dumps([job.model_dump() for job in pipeline.jobs], default=_json_default),
                error_detail,
                now,
            ),
        )
        db.commit()


def _row_to_pipeline(row: sqlite3.Row) -> PipelineResponse:
    jobs = [PipelineJob.model_validate(item) for item in json.loads(row["jobs_json"] or "[]")]
    return PipelineResponse(
        id=row["id"],
        status=PipelineStatus(row["status"]),
        trigger=row["trigger"],
        branch=row["branch"],
        started_at=datetime.fromisoformat(row["started_at"]),
        finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
        message=row["message"],
        copilot_reply=row["copilot_reply"],
        copilot_role=row["copilot_role"],
        delegation_target=row["delegation_target"],
        jobs=jobs,
    )


def _get(pipeline_id: str) -> PipelineResponse | None:
    with _db() as db:
        row = db.execute("SELECT * FROM pipeline_runs WHERE id=?", (pipeline_id,)).fetchone()
    return _row_to_pipeline(row) if row else None


async def _run_pipeline(pipeline: PipelineResponse, payload: dict) -> PipelineResponse:
    pipeline.status = PipelineStatus.RUNNING
    pipeline.message = pipeline_reply(PipelineStatus.RUNNING)
    pipeline.copilot_reply = pipeline.message
    if pipeline.jobs:
        pipeline.jobs[0].status = PipelineStatus.RUNNING
        pipeline.jobs[0].started_at = datetime.now(timezone.utc)
        pipeline.jobs[0].logs.append(pipeline.message)
    _save(pipeline, payload)

    try:
        if payload.get("trigger") == "autonomous":
            from amoscloud_ai.autonomous_server import run_autonomous_server

            run_payload = payload.get("payload", {})
            result = run_autonomous_server(
                run_payload.get("mode", "autonomous-check"),
                run_payload.get("objective", "amosclaud.com autonomous operations"),
                run_payload.get("metadata", {}),
            )
            successful = result.status == PipelineStatus.SUCCESS
            if pipeline.jobs:
                pipeline.jobs[0].logs.extend(result.logs)
        else:
            from src.core.ci_orchestrator import CIOrchestrator

            orchestrator = CIOrchestrator(config=payload)
            successful = await orchestrator.start_pipeline(payload.get("trigger", "manual"), payload)
            if orchestrator.jobs:
                pipeline.jobs = orchestrator.jobs

        pipeline.status = PipelineStatus.SUCCESS if successful else PipelineStatus.FAILED
        pipeline.finished_at = datetime.now(timezone.utc)
        pipeline.message = pipeline_reply(pipeline.status)
        pipeline.copilot_reply = pipeline.message
        if pipeline.jobs:
            pipeline.jobs[0].status = pipeline.status
            pipeline.jobs[0].finished_at = pipeline.finished_at
            pipeline.jobs[0].logs.append(pipeline.message)
        _save(pipeline, payload)
        return pipeline
    except Exception as exc:
        log.exception("Pipeline %s failed", pipeline.id)
        pipeline.status = PipelineStatus.FAILED
        pipeline.finished_at = datetime.now(timezone.utc)
        pipeline.message = f"Pipeline failed: {exc}"
        pipeline.copilot_reply = f"Amosclaud Autonomous Server: pipeline failed safely and recorded {type(exc).__name__}."
        for job in pipeline.jobs:
            if job.status not in (PipelineStatus.SUCCESS, PipelineStatus.CANCELLED):
                job.status = PipelineStatus.FAILED
                job.finished_at = pipeline.finished_at
                job.logs.append(str(exc))
        _save(pipeline, payload, str(exc))
        return pipeline


@router.get("", response_model=List[PipelineResponse], summary="List all pipelines")
async def list_pipelines() -> List[PipelineResponse]:
    with _db() as db:
        rows = db.execute("SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT 100").fetchall()
    return [_row_to_pipeline(row) for row in rows]


@router.get("/{pipeline_id}", response_model=PipelineResponse, summary="Get a pipeline")
async def get_pipeline(pipeline_id: str) -> PipelineResponse:
    pipeline = _get(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id!r} not found")
    return pipeline


@router.post("", response_model=PipelineResponse, status_code=201, summary="Trigger a pipeline")
async def trigger_pipeline(body: PipelineTrigger) -> PipelineResponse:
    pipeline_id = str(uuid.uuid4())
    reply = pipeline_reply(PipelineStatus.PENDING)
    pipeline = PipelineResponse(
        id=pipeline_id,
        status=PipelineStatus.PENDING,
        trigger=body.trigger,
        branch=body.branch,
        started_at=datetime.now(timezone.utc),
        message=reply,
        copilot_reply=reply,
        copilot_role=COPILOT_ROLE,
        delegation_target=COPILOT_PIPELINE,
        jobs=[PipelineJob(id="build", name="Build", status=PipelineStatus.PENDING, logs=[reply])],
    )
    payload = body.model_dump()
    _save(pipeline, payload)
    return await _run_pipeline(pipeline, payload)


@router.delete("/{pipeline_id}", status_code=204, summary="Cancel a pipeline")
async def cancel_pipeline(pipeline_id: str) -> None:
    pipeline = _get(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id!r} not found")
    if pipeline.status in (PipelineStatus.SUCCESS, PipelineStatus.FAILED, PipelineStatus.CANCELLED):
        raise HTTPException(status_code=409, detail="Pipeline already finished")
    pipeline.status = PipelineStatus.CANCELLED
    pipeline.finished_at = datetime.now(timezone.utc)
    pipeline.message = pipeline_reply(PipelineStatus.CANCELLED)
    pipeline.copilot_reply = pipeline.message
    for job in pipeline.jobs:
        if job.status not in (PipelineStatus.SUCCESS, PipelineStatus.FAILED, PipelineStatus.CANCELLED):
            job.status = PipelineStatus.CANCELLED
            job.finished_at = pipeline.finished_at
            job.logs.append(pipeline.message)
    _save(pipeline)
