"""Autonomous Amosclaud server routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from amoscloud_ai.agent.assistant_system_template import ASSISTANT_SYSTEM_TEMPLATE
from amoscloud_ai.api.routes.auth import get_user_from_session
from amoscloud_ai.api.routes.autonomous_keys import authenticate_autonomous_key
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

AGENT_NAME = "Amosclaud Autonomous"
AGENT_OWNER = "Amosclaud"
AGENT_ROLE = ASSISTANT_SYSTEM_TEMPLATE.role
AGENT_HOME = "amosclaud.com"
AGENT_PIPELINE = "Amosclaud autonomous pipeline"
AGENT_MODE = "agent"
AGENT_SCOPE = [AGENT_HOME, AGENT_PIPELINE]
AGENT_DIRECTIVES = list(ASSISTANT_SYSTEM_TEMPLATE.principles)
ALLOWED_MODES = {"autonomous-check", "build", "fix", "deploy", "monitor"}
GREETING_WORDS = {
    "hi",
    "hello",
    "hey",
    "hiya",
    "yo",
    "good morning",
    "good afternoon",
    "good evening",
}
GUIDANCE_PHRASES = {
    "can you guide",
    "guide me",
    "help me",
    "how do i",
    "how can i",
    "how should i",
    "what should",
    "what can go wrong",
    "explain",
    "show me a plan",
    "give me a plan",
    "easier way",
    "right solution",
    "best solution",
    "what is",
    "why is",
    "why does",
}
ACTION_WORDS = {
    "build",
    "create",
    "fix",
    "change",
    "delete",
    "deploy",
    "commit",
    "merge",
    "run",
    "test",
    "verify",
    "inspect",
    "monitor",
    "review",
    "publish",
}
EXECUTION_PHRASES = {
    "do it",
    "proceed",
    "apply the fix",
    "make the changes",
    "execute",
    "start building",
    "start to build",
    "now start to build",
    "start the build",
    "build it",
    "begin building",
}
FOLLOW_UP_EXECUTION = EXECUTION_PHRASES | {
    "start",
    "start now",
    "fix it",
    "deploy it",
    "make it",
    "continue",
}


def _bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "").strip()
    scheme, separator, value = authorization.partition(" ")
    if separator and scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return None


def _authenticated_user(request: Request):
    user = get_user_from_session(request.cookies.get("amos_session"))
    if user:
        return user
    return authenticate_autonomous_key(_bearer_token(request))


def _agent_reply(status: PipelineStatus, mode: str, objective: str) -> str:
    if status == PipelineStatus.PENDING:
        return f"Queued {mode} task: {objective}"
    if status == PipelineStatus.RUNNING:
        return f"Working on {objective}: inspecting evidence, acting, and verifying."
    if status == PipelineStatus.SUCCESS:
        return ASSISTANT_SYSTEM_TEMPLATE.execution_summary(
            objective=objective,
            status="success",
            evidence=(f"The {mode} runtime completed with verified evidence.",),
        )
    if status == PipelineStatus.FAILED:
        return ASSISTANT_SYSTEM_TEMPLATE.execution_summary(
            objective=objective,
            status="blocked",
            evidence=("The runtime reported a blocking failure.",),
            next_action="Review the failing check and apply the smallest safe repair.",
        )
    return ASSISTANT_SYSTEM_TEMPLATE.execution_summary(
        objective=objective,
        status="cancelled",
    )


def _display_name(request: Request) -> str:
    user = _authenticated_user(request)
    if not user:
        return ""
    raw_name = str(user["name"] or "").strip()
    first_name = raw_name.split()[0] if raw_name else ""
    return first_name[:1].upper() + first_name[1:] if first_name else ""


def _normalise(value: str) -> str:
    return " ".join((value or "").lower().rstrip(".!?").split())


def _resolve_follow_up(objective: str, metadata: dict | None) -> tuple[str, bool]:
    """Attach a short execution follow-up to the prior conversational objective."""

    current = objective.strip()
    normalised = _normalise(current)
    prepared = dict(metadata or {})
    previous = str(prepared.get("previous_objective") or "").strip()
    is_execution = normalised in FOLLOW_UP_EXECUTION
    if previous and is_execution:
        return f"Build the previously discussed outcome: {previous}", True
    return current, False


def _is_guidance_request(message: str, mode: str) -> bool:
    normalised = " ".join(message.lower().split())
    if not normalised:
        return False
    explicitly_execute = any(phrase in normalised for phrase in EXECUTION_PHRASES)
    asks_for_guidance = "?" in message or any(
        phrase in normalised for phrase in GUIDANCE_PHRASES
    )
    if mode == "autonomous-check" and not explicitly_execute:
        has_action = any(word in normalised.split() for word in ACTION_WORDS)
        return asks_for_guidance or not has_action
    return asks_for_guidance and not explicitly_execute


def _conversation_reply(request: Request, mode: str, objective: str) -> str | None:
    """Return a natural answer only when no engineering execution is required."""

    name = _display_name(request)
    message = objective.strip()
    normalised = _normalise(message)

    if not message and mode in {"build", "fix"}:
        return ASSISTANT_SYSTEM_TEMPLATE.missing_objective(mode, name)
    if normalised in GREETING_WORDS:
        return ASSISTANT_SYSTEM_TEMPLATE.greeting(name)
    if _is_guidance_request(message, mode):
        return ASSISTANT_SYSTEM_TEMPLATE.guidance(message)
    if normalised in {"build", "make", "create", "fix"}:
        return ASSISTANT_SYSTEM_TEMPLATE.missing_objective(normalised, name)
    return None


def _agent_metadata(mode: str, metadata: dict | None) -> tuple[str, dict]:
    prepared = dict(metadata or {})
    prepared["requested_mode"] = mode
    prepared.setdefault("agent_workflow", True)
    prepared.setdefault(
        "phases",
        ["understand", "inspect", "plan", "act", "verify", "report"],
    )
    prepared.setdefault("assistant_template_version", ASSISTANT_SYSTEM_TEMPLATE.version)
    execution_mode = mode
    if mode in {"build", "fix"}:
        execution_mode = "build"
        prepared.setdefault("use_agent", True)
        prepared.setdefault("apply_changes", mode == "fix")
    return execution_mode, prepared


@router.get(
    "",
    response_model=AutonomousAgentProfile,
    summary="Get autonomous agent profile",
)
async def get_agent() -> AutonomousAgentProfile:
    return AutonomousAgentProfile(
        name=AGENT_NAME,
        owner=AGENT_OWNER,
        role=AGENT_ROLE,
        mission=(
            "Answer naturally when the user is talking, and use the governed "
            "Autonomous pipeline when the user requests engineering work."
        ),
        mode=AGENT_MODE,
        home=AGENT_HOME,
        pipeline=AGENT_PIPELINE,
        scope=AGENT_SCOPE,
        directives=AGENT_DIRECTIVES,
    )


@router.post(
    "/run",
    response_model=AutonomousAgentRunResponse,
    summary="Start an autonomous agent task",
)
async def run_agent(
    body: AutonomousAgentRunRequest,
    request: Request,
) -> AutonomousAgentRunResponse:
    mode = body.mode.strip().lower()
    if mode not in ALLOWED_MODES:
        choices = ", ".join(sorted(ALLOWED_MODES))
        raise HTTPException(status_code=422, detail=f"Mode must be one of: {choices}")

    user = _authenticated_user(request)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Sign in or provide a valid Amosclaud Autonomous bearer key",
        )

    started_at = datetime.now(timezone.utc)
    run_id = str(uuid.uuid4())
    supplied_objective = (body.objective or "").strip()
    objective, continued = _resolve_follow_up(supplied_objective, body.metadata)
    conversational_reply = None if continued else _conversation_reply(
        request,
        mode,
        objective,
    )
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
            logs=["Conversational response returned without engineering execution."],
        )

    from amoscloud_ai.api.routes.pipelines import _save

    pipeline_id = str(uuid.uuid4())
    objective = objective or f"{AGENT_HOME} autonomous operations"
    execution_mode, metadata = _agent_metadata(mode, body.metadata)
    metadata.setdefault("authenticated_user_id", int(user["id"]))
    metadata.setdefault(
        "authentication",
        "autonomous-key" if _bearer_token(request) else "session",
    )
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
        jobs=[
            PipelineJob(
                id="autonomous-run",
                name="Agent Task",
                status=PipelineStatus.PENDING,
                logs=[reply],
            )
        ],
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
        ]
    except Exception as dispatch_error:
        log.warning(
            "Background worker unavailable; running autonomous agent inline: %s",
            dispatch_error,
        )
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
                {
                    "name": check.name,
                    "status": check.status,
                    "summary": check.summary,
                    "details": check.details,
                }
                for check in result.checks
            ]
            logs = result.logs
            _save(pipeline, payload)
        except Exception as inline_error:
            log.exception("Autonomous agent inline task failed")
            pipeline.status = PipelineStatus.FAILED
            pipeline.finished_at = datetime.now(timezone.utc)
            reply = ASSISTANT_SYSTEM_TEMPLATE.execution_summary(
                objective=objective,
                status="failed",
                evidence=(f"Runtime error: {type(inline_error).__name__}",),
                next_action="Review the server log and repair the first verified root cause.",
            )
            pipeline.message = reply
            pipeline.copilot_reply = reply
            if pipeline.jobs:
                pipeline.jobs[0].status = PipelineStatus.FAILED
                pipeline.jobs[0].started_at = started_at
                pipeline.jobs[0].finished_at = pipeline.finished_at
                pipeline.jobs[0].logs.append(
                    f"Runtime error: {type(inline_error).__name__}: {inline_error}"
                )
            checks = []
            logs = [reply, f"Runtime error: {type(inline_error).__name__}"]
            _save(pipeline, payload, str(inline_error))

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
