"""Autonomous Amosclaud server routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request

from amoscloud_ai.api.routes.auth import get_user_from_session
from amoscloud_ai.api.routes.chat import _authorize_platform_key, _is_owner
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

router = APIRouter(prefix="/agent", tags=["autonomous-runtime"])

AGENT_NAME = "Amosclaud Autonomous Agent"
AGENT_OWNER = "Amosclaud"
AGENT_ROLE = "controlled autonomous engineering and operations agent"
AGENT_HOME = "amosclaud.com"
AGENT_PIPELINE = "Amosclaud autonomous pipeline"
AGENT_MODE = "agent"
AGENT_SCOPE = [AGENT_HOME, AGENT_PIPELINE]
AGENT_DIRECTIVES = [
    "Understand the requested outcome before acting.",
    "Inspect repository and runtime evidence before proposing a change.",
    "Plan the smallest safe action and identify whether approval is required.",
    "Build or fix only inside the authorized workspace.",
    "Run verification after every applied change.",
    "Report exact actions, evidence, failures, and recommended next steps.",
]
ALLOWED_MODES = {"autonomous-check", "build", "fix", "deploy", "monitor"}
GREETING_WORDS = {"hi", "hello", "hey", "hiya", "yo", "good morning", "good afternoon", "good evening"}
FOLLOW_UP_EXECUTION = {
    "do it", "proceed", "start", "start now", "build it", "fix it", "deploy it",
    "now start to build", "start to build", "start building", "make it", "continue",
}


def _agent_reply(status: PipelineStatus, mode: str, objective: str) -> str:
    if status == PipelineStatus.PENDING:
        return f"{AGENT_NAME}: {mode} task queued. Objective: {objective}."
    if status == PipelineStatus.RUNNING:
        return f"{AGENT_NAME}: inspecting, planning, acting, and verifying {objective}."
    if status == PipelineStatus.SUCCESS:
        return f"{AGENT_NAME}: {mode} task completed with verified evidence for {objective}."
    if status == PipelineStatus.FAILED:
        return f"{AGENT_NAME}: {mode} task found a blocker for {objective}. Review the evidence and next action."
    return f"{AGENT_NAME}: {mode} task was cancelled for {objective}."


def _display_name(request: Request) -> str:
    user = get_user_from_session(request.cookies.get("amos_session"))
    if not user:
        return "there"
    raw_name = (user["name"] or "there").strip()
    first_name = raw_name.split()[0] if raw_name else "there"
    return first_name[:1].upper() + first_name[1:]


def _normalise(value: str) -> str:
    return " ".join((value or "").lower().rstrip(".!?").split())


def _resolve_follow_up(objective: str, metadata: dict | None) -> tuple[str, bool]:
    current = objective.strip()
    previous = str(dict(metadata or {}).get("previous_objective") or "").strip()
    if previous and _normalise(current) in FOLLOW_UP_EXECUTION:
        return f"Build the previously discussed outcome: {previous}", True
    return current, False


def _conversation_reply(request: Request, mode: str, objective: str) -> str | None:
    normalised = _normalise(objective)
    if not objective and mode in {"build", "fix"}:
        return f"Hi {_display_name(request)}. Describe the result you want and what must be true before I report success."
    if normalised in GREETING_WORDS:
        return (
            f"Hi {_display_name(request)}. Amosclaud Autonomous Agent is online. "
            "I can inspect, plan, build, fix, verify, deploy, or monitor."
        )
    return None


def _agent_metadata(mode: str, metadata: dict | None, auth_method: str) -> tuple[str, dict]:
    prepared = dict(metadata or {})
    prepared["requested_mode"] = mode
    prepared["auth_method"] = auth_method
    prepared.setdefault("agent_workflow", True)
    prepared.setdefault("phases", ["understand", "inspect", "plan", "act", "verify", "report"])
    execution_mode = mode
    if mode in {"build", "fix"}:
        execution_mode = "build"
        prepared.setdefault("use_agent", True)
        # Codex-style task requests execute after planning unless the caller
        # deliberately asks for plan-only mode with apply_changes=false.
        prepared.setdefault("apply_changes", True)
    return execution_mode, prepared


async def _authorize_request(
    request: Request,
    x_amosclaud_owner_key: Optional[str],
    x_api_key: Optional[str],
) -> str:
    if get_user_from_session(request.cookies.get("amos_session")):
        return "session"
    if _is_owner(x_amosclaud_owner_key):
        return "owner-key"
    if x_api_key:
        # Unlike the public chat route, autonomous execution always requires a
        # valid key when no signed-in browser session is present.
        await _authorize_platform_key(x_api_key, None)
        return "api-key"
    raise HTTPException(
        status_code=401,
        detail=(
            "Sign in or provide X-Amosclaud-Owner-Key or a valid X-API-Key "
            "to run Amosclaud Autonomous."
        ),
    )


@router.get("", response_model=AutonomousAgentProfile, summary="Get autonomous agent profile")
async def get_agent() -> AutonomousAgentProfile:
    return AutonomousAgentProfile(
        name=AGENT_NAME,
        owner=AGENT_OWNER,
        role=AGENT_ROLE,
        mission=(
            f"{AGENT_NAME} turns an objective into a controlled plan, performs authorized "
            f"repository or runtime actions, verifies the result, and reports evidence for {AGENT_HOME}."
        ),
        mode=AGENT_MODE,
        home=AGENT_HOME,
        pipeline=AGENT_PIPELINE,
        scope=AGENT_SCOPE,
        directives=AGENT_DIRECTIVES,
    )


@router.post("/run", response_model=AutonomousAgentRunResponse, summary="Start an autonomous agent task")
async def run_agent(
    body: AutonomousAgentRunRequest,
    request: Request,
    x_amosclaud_owner_key: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> AutonomousAgentRunResponse:
    mode = body.mode.strip().lower()
    if mode not in ALLOWED_MODES:
        raise HTTPException(status_code=422, detail=f"Mode must be one of: {', '.join(sorted(ALLOWED_MODES))}")

    auth_method = await _authorize_request(request, x_amosclaud_owner_key, x_api_key)
    started_at = datetime.now(timezone.utc)
    run_id = str(uuid.uuid4())
    supplied_objective = (body.objective or "").strip()
    objective, continued = _resolve_follow_up(supplied_objective, body.metadata)
    conversational_reply = None if continued else _conversation_reply(request, mode, objective)
    if conversational_reply:
        return AutonomousAgentRunResponse(
            accepted=True,
            run_id=run_id,
            mode=mode,
            objective=objective or "conversation",
            reply=conversational_reply,
            pipeline_id=f"conversation-{run_id}",
            status=PipelineStatus.SUCCESS,
            started_at=started_at,
            checks=[],
            logs=["Conversation response delivered without starting an engineering task."],
        )

    from amoscloud_ai.api.routes.pipelines import _save

    pipeline_id = str(uuid.uuid4())
    objective = objective or f"{AGENT_HOME} autonomous operations"
    execution_mode, metadata = _agent_metadata(mode, body.metadata, auth_method)
    if continued:
        metadata["conversation_continuation"] = True
        metadata["original_follow_up"] = supplied_objective
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
        jobs=[PipelineJob(id="autonomous-run", name="Agent Task", status=PipelineStatus.PENDING, logs=[reply])],
    )
    payload = {
        "trigger": "autonomous",
        "branch": body.branch,
        "commit_sha": None,
        "payload": {
            "run_id": run_id,
            "mode": execution_mode,
            "requested_mode": mode,
            "objective": objective,
            "metadata": metadata,
        },
    }
    _save(pipeline, payload)

    try:
        from amoscloud_ai.worker import run_pipeline_task

        dispatch_task(run_pipeline_task, pipeline_id, payload)
        checks = []
        logs = [
            reply,
            "Agent phases: understand → inspect → plan → act → verify → report",
            f"Poll /api/v1/pipelines/{pipeline_id} for the verified result.",
        ]
    except Exception as dispatch_error:
        log.warning("Background worker unavailable; running autonomous agent inline: %s", type(dispatch_error).__name__)
        try:
            result = run_autonomous_server(execution_mode, objective, metadata)
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
                {"name": check.name, "status": check.status, "summary": check.summary, "details": check.details}
                for check in result.checks
            ]
            logs = result.logs
            _save(pipeline, payload)
        except Exception as inline_error:
            log.exception("Autonomous agent inline task failed")
            pipeline.status = PipelineStatus.FAILED
            pipeline.finished_at = datetime.now(timezone.utc)
            reply = f"{AGENT_NAME}: task stopped safely for {objective}."
            pipeline.message = reply
            pipeline.copilot_reply = reply
            if pipeline.jobs:
                pipeline.jobs[0].status = PipelineStatus.FAILED
                pipeline.jobs[0].started_at = started_at
                pipeline.jobs[0].finished_at = pipeline.finished_at
                pipeline.jobs[0].logs.append(f"Runtime failure category: {type(inline_error).__name__}")
            checks = []
            logs = [reply, f"Runtime failure category: {type(inline_error).__name__}"]
            _save(pipeline, payload, type(inline_error).__name__)

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
