"""HTTP control interface pointing every request to one Autonomous orchestrator."""
from __future__ import annotations

from dataclasses import asdict
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.agent.actions import run_autonomous
from src.agent.autonomy_supervisor import AutonomySupervisor
from src.agent.cloud_agent import chat_with_autonomous
from src.agent.mini_autonomous import run_mini_autonomous
from .schemas import (
    AutonomousTaskRequest,
    AutonomousTaskResponse,
    CloudAgentChatRequest,
    MiniAutonomousRequest,
)

router = APIRouter(prefix="/api/v2/autonomous", tags=["autonomous"])
supervisor = AutonomySupervisor()


class MissionRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=8000)
    max_attempts: int = Field(default=3, ge=1, le=5)


class ApprovalDecision(BaseModel):
    approved: bool


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
    return chat_with_autonomous(payload.message, payload.evidence)


@router.post("/mini")
def mini_autonomous(payload: MiniAutonomousRequest) -> dict:
    return run_mini_autonomous(payload.issue, workspace=payload.workspace, authorized_writes=payload.authorized_writes)


@router.post("/missions")
def create_mission(payload: MissionRequest) -> dict:
    return asdict(supervisor.create_mission(payload.objective, payload.max_attempts))


@router.get("/missions")
def list_missions(limit: int = 50) -> list[dict]:
    return supervisor.list_missions(limit)


@router.get("/missions/{mission_id}")
def get_mission(mission_id: str) -> dict:
    try:
        return asdict(supervisor.get(mission_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/approvals/{approval_id}")
def decide_approval(approval_id: str, payload: ApprovalDecision) -> dict:
    try:
        return supervisor.decide_approval(approval_id, payload.approved)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/heartbeat")
def heartbeat() -> dict:
    return supervisor.heartbeat()


@router.get("/readiness")
def readiness() -> dict:
    return supervisor.readiness()


@router.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ready",
        "orchestrator": "AutonomousOrchestrator",
        "brain": "RollImageEngine",
        "cloud_agent": True,
        "mini_autonomous": True,
        "autonomy_supervisor": True,
        "single_entry_point": True,
        "paths": [
            "/api/v2/autonomous/run",
            "/api/v2/autonomous/chat",
            "/api/v2/autonomous/mini",
            "/api/v2/autonomous/missions",
            "/api/v2/autonomous/readiness",
        ],
    }
