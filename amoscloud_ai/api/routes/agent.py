"""Autonomous Amosclaud server routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from amoscloud_ai.api.routes.auth import get_user_from_session
from amoscloud_ai.autonomous_server import run_autonomous_server
from amoscloud_ai.logger import log
from amoscloud_ai.models import (
    AutonomousAgentProfile,
    AutonomousAgentRunRequest,
    AutonomousAgentRunResponse,
    PipelineJob,
    PipelineResponse,
    PipelineStatus,
)
from amoscloud_ai.task_dispatch import dispatch_task

router = APIRouter(prefix="/agent", tags=["autonomous-agent"])

AGENT_NAME = "Amosclaud Autonomous Server"
AGENT_OWNER = "Amosclaud"
AGENT_ROLE = "autonomous build, deployment, and monitoring server"
AGENT_HOME = "amosclaud.com"
AGENT_PIPELINE = "Amosclaud autonomous pipeline"
AGENT_MODE = "autonomous"
AGENT_SCOPE = [AGENT_HOME, AGENT_PIPELINE]
AGENT_DIRECTIVES = [
    "Continuously check Amosclaud-owned application health.",
    "Run builds and tests through the Amosclaud pipeline.",
    "Deploy or prepare deployments when the configured pipeline allows it.",
    "Report run state through the server API and dashboard.",
]
ALLOWED_MODES = {"autonomous-check", "build", "deploy", "monitor"}
GREETING_WORDS = {"hi", "hello", "hey", "hiya", "yo", "good morning", "good afternoon", "good evening"}


def _agent_reply(status: PipelineStatus, mode: str, objective: str) -> str:
    if status == PipelineStatus.PENDING:
        return f"{AGENT_NAME}: autonomous {mode} run queued for {objective}."
    if status == PipelineStatus.RUNNING:
        return f"{AGENT_NAME}: autonomous {mode} run is active for {objective}."
    if status == PipelineStatus.SUCCESS:
        return f"{AGENT_NAME}: autonomous {mode} run completed for {objective}."
    if status == PipelineStatus.FAILED:
        return f"{AGENT_NAME}: autonomous {mode} run failed for {objective}."
    return f"{AGENT_NAME}: autonomous {mode} run was cancelled for {objective}."


def _display_name(request: Request) -> str:
    user = get_user_from_session(request.cookies.get("amos_session"))
    if not user:
        return "there"
    raw_name = (user["name"] or "there").strip()
    first_name = raw_name.split()[0] if raw_name else "there"
    return first_name[:1].upper() + first_name[1:]


def _conversation_reply(request: Request, mode: str, objective: str) -> str | None:
    name = _display_name(request)
    message = objective.strip()
    normalised = " ".join(message.lower().rstrip(".!?").split())

    if not message and mode == "build":
        return f"What would you like to build today, {name}?"

    if normalised in GREETING_WORDS:
        return f"Hi {name}. What would you like to build today?"

    if normalised in {"build", "make", "create"}:
        return f"What would you like to build today, {name}?"

    return None


@router.get("", response_model=AutonomousAgentProfile, summary="Get autonomous server profile")
async def get_agent() -> AutonomousAgentProfile:
    return AutonomousAgentProfile(
        name=AGENT_NAME,
        owner=AGENT_OWNER,
        role=AGENT_ROLE,
        mission=(
            f"{AGENT_NAME} runs Amosclaud-owned checks, builds, deployments, "
            f"and monitoring for {AGENT_HOME}."
        ),
        mode=AGENT_MODE,
        home=AGENT_HOME,
        pipeline=AGENT_PIPELINE,
        scope=AGENT_SCOPE,
        directives=AGENT_DIRECTIVES,
    )


@router.post("/run", response_model=AutonomousAgentRunResponse, summary="Start an autonomous server run")
async def run_agent(body: AutonomousAgentRunRequest, request: Request) -> AutonomousAgentRunResponse:
    mode = body.mode.strip().lower()
    if mode not in ALLOWED_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"Mode must be one of: {', '.join(sorted(ALLOWED_MODES))}",
        )

    started_at = datetime.now(timezone.utc)
    run_id = str(uuid.uuid4())
    objective = (body.objective or "").strip()

    conversational_reply = _conversation_reply(request, mode, objective)
    if conversational_reply:
        return AutonomousAgentRunResponse(
            accepted=True,
            run_id=run_id,
            mode=mode,
            objective=objective or "conversation",
            reply=conversational_reply,
            pipeline_id=f"chat-{run_id}",
            status=PipelineStatus.SUCCESS,
            started_at=started_at,
            checks=[],
            logs=[conversational_reply],
        )

    from amoscloud_ai.api.routes.pipelines import _pipelines

    pipeline_id = str(uuid.uuid4())
    objective = objective or f"{AGENT_HOME} autonomous operations"
    reply = _agent_reply(PipelineStatus.PENDING, mode, objective)

    pipeline = PipelineResponse(
        id=pipeline_id,
        status=PipelineStatus.PENDING,
        trigger="autonomous",
        branch=body.branch,
        started_at=started_at,
        message=reply,
        copilot_reply=reply,
        copilot_role=AGENT_ROLE,
        delegation_target=AGENT_PIPELINE,
        jobs=[
            PipelineJob(
                id="autonomous-run",
                name="Autonomous Run",
                status=PipelineStatus.PENDING,
                logs=[reply],
            )
        ],
    )
    _pipelines[pipeline_id] = pipeline

    payload = {
        "trigger": "autonomous",
        "branch": body.branch,
        "commit_sha": None,
        "payload": {
            "run_id": run_id,
            "mode": mode,
            "objective": objective,
            "metadata": body.metadata,
        },
    }

    try:
        from amoscloud_ai.worker import run_pipeline_task

        dispatch_task(run_pipeline_task, pipeline_id, payload)
    except Exception:
        log.warning("Celery unavailable - running autonomous server inline")
        result = run_autonomous_server(mode, objective, body.metadata)
        pipeline.status = result.status
        pipeline.finished_at = datetime.now(timezone.utc)
        reply = result.reply
        pipeline.message = reply
        pipeline.copilot_reply = reply
        if pipeline.jobs:
            pipeline.jobs[0].status = result.status
            pipeline.jobs[0].started_at = started_at
            pipeline.jobs[0].finished_at = pipeline.finished_at
            pipeline.jobs[0].logs.extend(result.logs)
        checks = [
            {
                "name": check.name,
                "status": check.status,
                "summary": check.summary,
                "details": check.details,
            }
            for check in result.checks
        ]
        logs = result.logs
    else:
        checks = []
        logs = [reply]

    return AutonomousAgentRunResponse(
        accepted=True,
        run_id=run_id,
        mode=mode,
        objective=objective,
        reply=pipeline.copilot_reply or reply,
        pipeline_id=pipeline_id,
        status=pipeline.status,
        started_at=started_at,
        checks=checks,
        logs=logs,
    )
