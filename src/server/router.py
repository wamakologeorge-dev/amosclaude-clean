"""HTTP control interface pointing every request to one Autonomous orchestrator."""
from __future__ import annotations

from fastapi import APIRouter

from src.agent.actions import run_autonomous
from src.agent.cloud_agent import chat_with_autonomous
from src.agent.mini_autonomous import run_mini_autonomous
from .schemas import (
    AutonomousTaskRequest,
    AutonomousTaskResponse,
    CloudAgentChatRequest,
    MiniAutonomousRequest,
)

router = APIRouter(prefix="/api/v2/autonomous", tags=["autonomous"])


@router.post("/run", response_model=AutonomousTaskResponse)
def run_task(payload: AutonomousTaskRequest) -> dict:
    return run_autonomous(
        objective=payload.objective,
        mode=payload.mode,
        authorized_writes=payload.authorized_writes,
        workspace=payload.workspace,
    )


@router.post("/chat")
def cloud_agent_chat(payload: CloudAgentChatRequest) -> dict:
    """Text the Cloud Agent and receive an evidence-grounded reply."""
    return chat_with_autonomous(payload.message, payload.evidence)


@router.post("/mini")
def mini_autonomous(payload: MiniAutonomousRequest) -> dict:
    """Send an issue through RollImage and the central engineering loop."""
    return run_mini_autonomous(
        payload.issue,
        workspace=payload.workspace,
        authorized_writes=payload.authorized_writes,
    )


@router.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ready",
        "orchestrator": "AutonomousOrchestrator",
        "brain": "RollImageEngine",
        "cloud_agent": True,
        "mini_autonomous": True,
        "single_entry_point": True,
        "paths": [
            "/api/v2/autonomous/run",
            "/api/v2/autonomous/chat",
            "/api/v2/autonomous/mini",
        ],
    }
