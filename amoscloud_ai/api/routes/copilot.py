"""Repository-aware Amosclaud Copilot API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from amoscloud_ai.api.routes.agent import _authenticated_user, run_agent
from amoscloud_ai.copilot import (
    COPILOT_ASSISTANT_ROLE,
    COPILOT_PIPELINE,
    COPILOT_SCOPE,
    available_agents,
    build_copilot_plan,
    copilot_profile,
)
from amoscloud_ai.models import (
    AutonomousAgentRunRequest,
    CopilotDelegationRequest,
    CopilotDelegationResponse,
)

router = APIRouter(prefix="/copilot", tags=["copilot"])


class CopilotContext(BaseModel):
    """Bounded editor and repository context supplied by a Copilot client."""

    repository: str | None = Field(default=None, max_length=255)
    branch: str = Field(default="main", min_length=1, max_length=255, pattern=r"^[A-Za-z0-9._/-]+$")
    file_path: str | None = Field(default=None, max_length=1024)
    selection: str | None = Field(default=None, max_length=16000)
    language: str | None = Field(default=None, max_length=64)
    source: str | None = Field(default="amosclaud-copilot", max_length=128)


class CopilotRequest(BaseModel):
    task: str = Field(..., min_length=1, max_length=12000)
    requested_agent: str | None = Field(default=None, max_length=128)
    context: CopilotContext = Field(default_factory=CopilotContext)


def _require_user(request: Request) -> Any:
    user = _authenticated_user(request)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Sign in or provide a valid Amosclaud Autonomous bearer key",
        )
    return user


def _create_plan(body: CopilotRequest) -> dict[str, object]:
    context = body.context
    try:
        return build_copilot_plan(
            body.task,
            requested_agent=body.requested_agent,
            repository=context.repository,
            branch=context.branch,
            file_path=context.file_path,
            selection=context.selection,
            language=context.language,
            source=context.source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", summary="Get Amosclaud Copilot profile")
async def get_copilot() -> dict[str, object]:
    return copilot_profile()


@router.get("/agents", summary="List agents coordinated by Amosclaud Copilot")
async def list_copilot_agents() -> dict[str, object]:
    agents = available_agents()
    return {"agents": agents, "count": len(agents)}


@router.post("/plan", summary="Plan a repository-aware Copilot task")
async def plan_copilot_task(body: CopilotRequest, request: Request) -> dict[str, object]:
    _require_user(request)
    return _create_plan(body)


@router.post("/run", summary="Route and run a Copilot task through Amosclaud Autonomous")
async def run_copilot_task(body: CopilotRequest, request: Request) -> dict[str, object]:
    _require_user(request)
    plan = _create_plan(body)
    handoff = plan["handoff"]
    payload = handoff["payload"]
    run_request = AutonomousAgentRunRequest(**payload)
    result = await run_agent(run_request, request)
    return {
        "accepted": result.accepted,
        "plan": plan,
        "execution": result.model_dump(mode="json"),
    }


@router.post(
    "/delegate",
    response_model=CopilotDelegationResponse,
    summary="Delegate work to Amosclaud Copilot (compatibility endpoint)",
)
async def delegate_to_copilot(
    body: CopilotDelegationRequest,
    request: Request,
) -> CopilotDelegationResponse:
    """Preserve the original endpoint while using the real agent coordinator."""

    _require_user(request)
    metadata = dict(body.metadata or {})
    try:
        context = CopilotContext(
            repository=str(metadata.get("repository") or "") or None,
            branch=str(metadata.get("branch") or "main"),
            file_path=str(metadata.get("file_path") or "") or None,
            selection=str(metadata.get("selection") or "") or None,
            language=str(metadata.get("language") or "") or None,
            source=body.source or str(metadata.get("source") or "") or "copilot-delegate",
        )
        request_body = CopilotRequest(
            task=body.task,
            requested_agent=str(metadata.get("requested_agent") or "") or None,
            context=context,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response = await run_copilot_task(request_body, request)
    plan = response["plan"]
    execution = response["execution"]
    primary = plan["primary_agent"]
    return CopilotDelegationResponse(
        accepted=bool(execution["accepted"]),
        task=body.task.strip(),
        source=body.source,
        reply=str(execution["reply"]),
        copilot_role=COPILOT_ASSISTANT_ROLE,
        delegation_target=f"{primary['name']} through {COPILOT_PIPELINE}",
        scope=COPILOT_SCOPE,
        pipeline_id=str(execution["pipeline_id"]),
        status=execution["status"],
        accepted_at=execution["started_at"],
    )
