"""Autonomous Amosclaud server routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

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
FOLLOW_UP_EXECUTION = {
    "do it",
    "proceed",
    "start",
    "start now",
    "build it",
    "fix it",
    "deploy it",
    "now start to build",
    "start to build",
    "start building",
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
        return f"{AGENT_NAME}: {mode} task queued. Objective: {objective}."
    if status == PipelineStatus.RUNNING:
        return f"{AGENT_NAME}: inspecting, planning, acting, and verifying {objective}."
    if status == PipelineStatus.SUCCESS:
        return f"{AGENT_NAME}: {mode} task completed with verified evidence for {objective}."
    if status == PipelineStatus.FAILED:
        return (
            f"{AGENT_NAME}: {mode} task found a blocker for {objective}. "
            "Review the evidence and next action."
        )
    return f"{AGENT_NAME}: {mode} task was cancelled for {objective}."


def _display_name(request: Request) -> str:
    user = _authenticated_user(request)
    if not user:
        return "there"
    raw_name = (user["name"] or "there").strip()
    first_name = raw_name.split()[0] if raw_name else "there"
    return first_name[:1].upper() + first_name[1:]


def _normalise(value: str) -> str:
    return " ".join((value or "").lower().rstrip(".!?").split())


def _resolve_follow_up(objective: str, metadata: dict | None) -> tuple[str, bool]:
    """Attach a short execution follow-up to the prior conversational objective."""
    current = objective.strip()
    normalised = _normalise(current)
    prepared = dict(metadata or {})
    previous = str(prepared.get("previous_objective") or "").strip()
    is_execution = normalised in FOLLOW_UP_EXECUTION or any(
        phrase == normalised for phrase in EXECUTION_PHRASES
    )
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


def _guidance_reply(request: Request, objective: str) -> str:
    name = _display_name(request)
    message = objective.strip()
    normalised = " ".join(message.lower().split())

    if "website" in normalised or "platform" in normalised:
        subject = "platform" if "platform" in normalised else "website"
        return (
            f"Hi {name}. Yes — I can guide you.\n\n"
            "Plan:\n"
            f"1. Define the {subject} purpose, users, and first successful workflow.\n"
            "2. Choose the simplest architecture that fits the goal.\n"
            "3. Design the interface, API contracts, database, and permissions.\n"
            "4. Build one complete vertical feature before adding more systems.\n"
            "5. Test security, accessibility, performance, recovery, and deployment.\n"
            "6. Verify a preview before publishing.\n\n"
            "What can go wrong: unclear requirements, too many early features, "
            "insecure secrets, broken permissions, lost data, and unverified deployment.\n\n"
            "Recommended solution: start with a small working version and expand "
            "after each verified milestone.\n\n"
            "Easier way: describe the platform name, purpose, first users, required "
            "pages, and whether I may create files. Then say ‘start to build’."
        )

    return (
        f"Hi {name}. I understand your question.\n\n"
        "Plan:\n"
        "1. Confirm the outcome you want.\n"
        "2. Inspect only the evidence related to that outcome.\n"
        "3. Explain the risks and possible failure points.\n"
        "4. Recommend the safest correct solution.\n"
        "5. Show an easier alternative when one exists.\n"
        "6. Execute only when authorized, then verify and point to the result.\n\n"
        "No repository tests were started because this was a guidance question."
    )


def _conversation_reply(
    request: Request,
    mode: str,
    objective: str,
) -> str | None:
    name = _display_name(request)
    message = objective.strip()
    normalised = _normalise(message)

    if not message and mode in {"build", "fix"}:
        return (
            f"Hi {name}. Describe the result you want, the repository or folder, "
            "and whether I may apply changes."
        )
    if normalised in GREETING_WORDS:
        return (
            f"Hi {name}. Amosclaud Autonomous Agent is online. I can answer "
            "questions, explain plans and risks, inspect, build, fix, verify, "
            "deploy, or monitor."
        )
    if _is_guidance_request(message, mode):
        return _guidance_reply(request, message)
    if normalised in {"build", "make", "create", "fix"}:
        return (
            f"Hi {name}. What outcome should I produce, and what must be true "
            "before I report success?"
        )
    return None


def _agent_metadata(mode: str, metadata: dict | None) -> tuple[str, dict]:
    prepared = dict(metadata or {})
    prepared["requested_mode"] = mode
    prepared.setdefault("agent_workflow", True)
    prepared.setdefault(
        "phases",
        ["understand", "inspect", "plan", "act", "verify", "report"],
    )
    execution_mode = mode
    if mode in {"build", "fix"}:
        execution_mode = "build"
        prepared.setdefault("use_agent", True)
        prepared.setdefault("apply_changes", mode == "fix")
    return execution_mode, prepared


def _has_passing_engineering_evidence(checks: list[dict]) -> bool:
    """Require at least one check and reject any failed or ambiguous check."""
    if not checks:
        return False
    return all(str(check.get("status", "")).lower() in {"pass", "passed", "success"} for check in checks)


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
            f"{AGENT_NAME} turns an objective into a controlled plan, performs "
            "authorized repository or runtime actions, verifies the result, and "
            f"reports evidence for {AGENT_HOME}."
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
            logs=[
                "Guidance response delivered. Engineering verification is not applicable because no code, file, deployment, or system change was claimed."
            ],
        )

    from amoscloud_ai.api.routes.pipelines import _save

    pipeline_id = str(uuid.uuid4())
    objective = objective or f"{AGENT_HOME} autonomous operations"
    execution_mode, metadata = _agent_metadata(mode, body.metadata)
    metadata.setdefault("authenticated_user_id", int(user["id"]))
    metadata.setdefault("authentication", "autonomous-key" if _bearer_token(request) else "session")
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
            if pipeline.status == PipelineStatus.SUCCESS and not _has_passing_engineering_evidence(checks):
                pipeline.status = PipelineStatus.FAILED
                reply = (
                    f"{AGENT_NAME}: work ran for {objective}, but engineering verification "
                    "did not produce complete passing evidence. The result is not verified."
                )
                pipeline.message = reply
                pipeline.copilot_reply = reply
                logs = [*logs, "Engineering completion blocked: passing verification evidence is required."]
                if pipeline.jobs:
                    pipeline.jobs[0].status = PipelineStatus.FAILED
                    pipeline.jobs[0].logs.append(logs[-1])
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
