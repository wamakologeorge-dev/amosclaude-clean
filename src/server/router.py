"""HTTP control interface for the single Amosclaud OS Autonomous kernel."""
from __future__ import annotations

import hmac
import os
from dataclasses import asdict

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from src.agent.autonomy_supervisor import AutonomySupervisor
from src.amosclaud_os import get_autonomous_kernel
from .schemas import AutonomousTaskRequest, AutonomousTaskResponse, CloudAgentChatRequest, MiniAutonomousRequest

router = APIRouter(prefix="/api/v2/autonomous", tags=["autonomous"])
supervisor = AutonomySupervisor()
SELF_KEY_ENV = "AMOSCLAUD_AUTONOMOUS_SELF_KEY"
SELF_KEY_HEADER = "X-Amosclaud-Autonomous-Key"


class MissionRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=8000)
    max_attempts: int = Field(default=3, ge=1, le=5)


class ApprovalDecision(BaseModel):
    approved: bool


def require_self_key(value: str | None) -> None:
    expected = os.getenv(SELF_KEY_ENV, "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail=f"{SELF_KEY_ENV} is not configured")
    supplied = (value or "").strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid Amosclaud Autonomous self key")


@router.post("/run", response_model=AutonomousTaskResponse)
def run_task(payload: AutonomousTaskRequest, self_key: str | None = Header(default=None, alias=SELF_KEY_HEADER)) -> dict:
    require_self_key(self_key)
    return get_autonomous_kernel(payload.workspace).execute(
        objective=payload.objective,
        mode=payload.mode,
        authorized_writes=payload.authorized_writes,
        metadata=payload.metadata,
    )


@router.post("/chat")
def cloud_agent_chat(payload: CloudAgentChatRequest, self_key: str | None = Header(default=None, alias=SELF_KEY_HEADER)) -> dict:
    require_self_key(self_key)
    return get_autonomous_kernel(payload.workspace).assist(
        message=payload.message,
        evidence=payload.evidence,
        result_locations=payload.result_locations,
        execute=payload.execute,
        authorized_writes=payload.authorized_writes,
    )


@router.post("/mini")
def mini_autonomous(payload: MiniAutonomousRequest, self_key: str | None = Header(default=None, alias=SELF_KEY_HEADER)) -> dict:
    require_self_key(self_key)
    return get_autonomous_kernel(payload.workspace).repair(
        issue=payload.issue,
        authorized_writes=payload.authorized_writes,
    )


@router.post("/missions")
def create_mission(payload: MissionRequest, self_key: str | None = Header(default=None, alias=SELF_KEY_HEADER)) -> dict:
    require_self_key(self_key)
    return asdict(supervisor.create_mission(payload.objective, payload.max_attempts))


@router.get("/missions")
def list_missions(limit: int = 50, self_key: str | None = Header(default=None, alias=SELF_KEY_HEADER)) -> list[dict]:
    require_self_key(self_key)
    return supervisor.list_missions(limit)


@router.get("/missions/{mission_id}")
def get_mission(mission_id: str, self_key: str | None = Header(default=None, alias=SELF_KEY_HEADER)) -> dict:
    require_self_key(self_key)
    try:
        return asdict(supervisor.get(mission_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/approvals/{approval_id}")
def decide_approval(approval_id: str, payload: ApprovalDecision, self_key: str | None = Header(default=None, alias=SELF_KEY_HEADER)) -> dict:
    require_self_key(self_key)
    try:
        return supervisor.decide_approval(approval_id, payload.approved)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/heartbeat")
def heartbeat(self_key: str | None = Header(default=None, alias=SELF_KEY_HEADER)) -> dict:
    require_self_key(self_key)
    return supervisor.heartbeat()


@router.get("/readiness")
def readiness(self_key: str | None = Header(default=None, alias=SELF_KEY_HEADER)) -> dict:
    require_self_key(self_key)
    return supervisor.readiness()


@router.get("/os")
def os_status() -> dict:
    """Public identity and readiness for the single Amosclaud OS driver."""
    return get_autonomous_kernel().status()


@router.get("/health")
def health() -> dict[str, object]:
    kernel = get_autonomous_kernel()
    return {
        **kernel.status(),
        "brain": "AutonomousOrchestrator",
        "working_context": "RollImageEngine",
        "cloud_agent": True,
        "agent_assistant": True,
        "mini_autonomous": True,
        "autonomy_supervisor": True,
        "self_key_required": True,
        "self_key_environment": SELF_KEY_ENV,
        "self_key_header": SELF_KEY_HEADER,
        "single_entry_point": True,
        "paths": [
            "/api/v2/autonomous/run",
            "/api/v2/autonomous/chat",
            "/api/v2/autonomous/mini",
            "/api/v2/autonomous/missions",
            "/api/v2/autonomous/readiness",
            "/api/v2/autonomous/os",
        ],
    }
