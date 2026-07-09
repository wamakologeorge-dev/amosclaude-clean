"""Amosclaud Copilot route."""

from fastapi import APIRouter, HTTPException

from amoscloud_ai.copilot import (
    COPILOT_PIPELINE,
    COPILOT_ROLE,
    COPILOT_SCOPE,
    copilot_profile,
)
from amoscloud_ai.models import (
    CopilotDelegationRequest,
    CopilotDelegationResponse,
    CopilotProfile,
)

router = APIRouter(prefix="/copilot", tags=["copilot"])


@router.get("", response_model=CopilotProfile, summary="Get Amosclaud Copilot profile")
async def get_copilot() -> CopilotProfile:
    return CopilotProfile(**copilot_profile())


@router.post("/delegate", response_model=CopilotDelegationResponse, summary="Delegate work to Amosclaud Copilot")
async def delegate_to_copilot(body: CopilotDelegationRequest) -> CopilotDelegationResponse:
    task = body.task.strip()
    if not task:
        raise HTTPException(status_code=422, detail="Task must not be blank")

    reply = (
        f"Amosclaud Copilot: I accepted this as {COPILOT_ROLE}. "
        f"I am delegating it into the {COPILOT_PIPELINE} and will report back."
    )
    return CopilotDelegationResponse(
        accepted=True,
        task=task,
        source=body.source,
        reply=reply,
        copilot_role=COPILOT_ROLE,
        delegation_target=COPILOT_PIPELINE,
        scope=COPILOT_SCOPE,
    )
