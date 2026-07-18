"""Pipeline management routes."""

import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, HTTPException

from amoscloud_ai.copilot import COPILOT_PIPELINE, COPILOT_ROLE, pipeline_reply
from amoscloud_ai.logger import log
from amoscloud_ai.models import PipelineJob, PipelineResponse, PipelineStatus, PipelineTrigger
from amoscloud_ai.task_dispatch import dispatch_task

router = APIRouter(prefix="/pipelines", tags=["pipelines"])

# In-memory store (replace with DB in production)
_pipelines: dict[str, PipelineResponse] = {}


@router.get("", response_model=List[PipelineResponse], summary="List all pipelines")
async def list_pipelines() -> List[PipelineResponse]:
    return list(_pipelines.values())


@router.get("/{pipeline_id}", response_model=PipelineResponse, summary="Get a pipeline")
async def get_pipeline(pipeline_id: str) -> PipelineResponse:
    pipeline = _pipelines.get(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id!r} not found")
    return pipeline


@router.post("", response_model=PipelineResponse, status_code=201, summary="Trigger a pipeline")
async def trigger_pipeline(body: PipelineTrigger) -> PipelineResponse:
    pipeline_id = str(uuid.uuid4())
    log.info(f"Triggering pipeline {pipeline_id} via {body.trigger}")
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
        jobs=[
            PipelineJob(
                id="build",
                name="Build",
                status=PipelineStatus.PENDING,
                logs=[reply],
            )
        ],
    )
    _pipelines[pipeline_id] = pipeline

    # Kick off background task (Celery task if broker available, otherwise inline stub)
    try:
        from amoscloud_ai.worker import run_pipeline_task
        dispatch_task(run_pipeline_task, pipeline_id, body.model_dump())
    except Exception:
        log.warning("Celery unavailable – running pipeline synchronously (stub)")
        pipeline.status = PipelineStatus.SUCCESS
        pipeline.finished_at = datetime.now(timezone.utc)
        reply = pipeline_reply(PipelineStatus.SUCCESS)
        pipeline.message = reply
        pipeline.copilot_reply = reply
        if pipeline.jobs:
            pipeline.jobs[0].status = PipelineStatus.SUCCESS
            pipeline.jobs[0].started_at = pipeline.started_at
            pipeline.jobs[0].finished_at = pipeline.finished_at
            pipeline.jobs[0].logs.append(reply)

    return pipeline


@router.delete("/{pipeline_id}", status_code=204, summary="Cancel a pipeline")
async def cancel_pipeline(pipeline_id: str) -> None:
    pipeline = _pipelines.get(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id!r} not found")
    if pipeline.status in (PipelineStatus.SUCCESS, PipelineStatus.FAILED, PipelineStatus.CANCELLED):
        raise HTTPException(status_code=409, detail="Pipeline already finished")
    pipeline.status = PipelineStatus.CANCELLED
    pipeline.finished_at = datetime.now(timezone.utc)
    reply = pipeline_reply(PipelineStatus.CANCELLED)
    pipeline.message = reply
    pipeline.copilot_reply = reply
    for job in pipeline.jobs:
        if job.status not in (PipelineStatus.SUCCESS, PipelineStatus.FAILED, PipelineStatus.CANCELLED):
            job.status = PipelineStatus.CANCELLED
            job.finished_at = pipeline.finished_at
            job.logs.append(reply)
    log.info(f"Pipeline {pipeline_id} cancelled")
