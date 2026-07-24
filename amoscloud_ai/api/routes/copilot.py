"""Amosclaud Copilot route."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from amoscloud_ai.copilot import (
    COPILOT_PIPELINE,
    COPILOT_ROLE,
    COPILOT_SCOPE,
    copilot_profile,
    pipeline_reply,
)
from amoscloud_ai.models import (
    CopilotDelegationRequest,
    CopilotDelegationResponse,
    CopilotProfile,
    PipelineJob,
    PipelineResponse,
    PipelineStatus,
)
from amoscloud_ai.task_dispatch import dispatch_task

router = APIRouter(prefix="/copilot", tags=["copilot"])


@router.get("", response_model=CopilotProfile, summary="Get Amosclaud Copilot profile")
async def get_copilot() -> CopilotProfile:
    return CopilotProfile(**copilot_profile())


@router.post("/delegate", response_model=CopilotDelegationResponse, summary="Delegate work to Amosclaud Copilot")
async def delegate_to_copilot(body: CopilotDelegationRequest) -> CopilotDelegationResponse:
    task = body.task.strip()
    if not task:
        raise HTTPException(status_code=422, detail="Task must not be blank")

    from amoscloud_ai.api.routes.pipelines import _pipelines

    accepted_at = datetime.now(timezone.utc)
    pipeline_id = str(uuid.uuid4())
    reply = pipeline_reply(PipelineStatus.PENDING)
    branch = body.metadata.get("branch", "main") if body.metadata else "main"
    pipeline = PipelineResponse(
        id=pipeline_id,
        status=PipelineStatus.PENDING,
        trigger="copilot",
        branch=branch,
        started_at=accepted_at,
        message=reply,
        copilot_reply=reply,
        copilot_role=COPILOT_ROLE,
        delegation_target=COPILOT_PIPELINE,
        jobs=[
            PipelineJob(
                id="copilot-delegation",
                name="Copilot Delegation",
                status=PipelineStatus.PENDING,
                logs=[reply, f"Task: {task}"],
            )
        ],
    )
    _pipelines[pipeline_id] = pipeline

    payload = {
        "trigger": "copilot",
        "branch": pipeline.branch,
        "commit_sha": None,
        "payload": {
            "task": task,
            "source": body.source,
            "metadata": body.metadata,
        },
    }

    try:
        from amoscloud_ai.worker import run_pipeline_task
        dispatch_task(run_pipeline_task, pipeline_id, payload)
    except Exception:
        pipeline.status = PipelineStatus.SUCCESS
        pipeline.finished_at = datetime.now(timezone.utc)
        reply = pipeline_reply(PipelineStatus.SUCCESS)
        pipeline.message = reply
        pipeline.copilot_reply = reply
        if pipeline.jobs:
            pipeline.jobs[0].status = PipelineStatus.SUCCESS
            pipeline.jobs[0].started_at = accepted_at
            pipeline.jobs[0].finished_at = pipeline.finished_at
            pipeline.jobs[0].logs.append(reply)

    response_reply = (
        f"{reply} Delegation id {pipeline_id} is now visible in pipelines."
    )
    return CopilotDelegationResponse(
        accepted=True,
        task=task,
        source=body.source,
        reply=response_reply,
        copilot_role=COPILOT_ROLE,
        delegation_target=COPILOT_PIPELINE,
        scope=COPILOT_SCOPE,
        pipeline_id=pipeline_id,
        status=pipeline.status,
        accepted_at=accepted_at,
    )
