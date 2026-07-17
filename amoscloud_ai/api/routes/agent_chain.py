"""Single public API route for all Amosclaud agent power."""
from __future__ import annotations

from fastapi import APIRouter, Request

from amoscloud_ai.agent_chain import MODE_SKILLS, agent_power_chain
from amoscloud_ai.api.routes.agent import run_agent
from amoscloud_ai.models import AutonomousAgentRunRequest, AutonomousAgentRunResponse

router = APIRouter(prefix="/agent-chain", tags=["agent-power-chain"])


@router.get("")
async def describe_agent_chain() -> dict:
    """Describe the canonical route and skills without exposing secrets."""
    return {
        "name": "Amosclaud Agent Power Chain",
        "version": "v1",
        "route": agent_power_chain.route,
        "authentication": ["amos_session cookie", "Bearer amos_aut_..."],
        "modes": MODE_SKILLS,
        "metadata_dashboard": {
            "page": "/static/metadata-dashboard.html",
            "api": "/api/v1/agent-chain/metadata/summary",
        },
        "flow": [
            "authenticate",
            "authorize skill",
            "attach chain context",
            "route to main Autonomous",
            "verify result",
            "return evidence",
        ],
    }


@router.post("/run", response_model=AutonomousAgentRunResponse)
async def run_agent_chain(
    body: AutonomousAgentRunRequest,
    request: Request,
) -> AutonomousAgentRunResponse:
    """Authorize once, then route through the existing main Autonomous."""
    context = agent_power_chain.authorize(request, body.mode)
    metadata = dict(body.metadata or {})
    metadata.update(context.metadata())

    chained_body = body.model_copy(update={"metadata": metadata})
    return await run_agent(chained_body, request)
