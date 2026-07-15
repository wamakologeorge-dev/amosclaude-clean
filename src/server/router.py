"""HTTP control interface pointing every request to one Autonomous orchestrator."""

from __future__ import annotations

from fastapi import APIRouter

from src.agent.actions import run_autonomous
from .schemas import AutonomousTaskRequest, AutonomousTaskResponse

router = APIRouter(prefix="/api/v2/autonomous", tags=["autonomous"])


@router.post("/run", response_model=AutonomousTaskResponse)
def run_task(payload: AutonomousTaskRequest) -> dict:
    return run_autonomous(
        objective=payload.objective,
        mode=payload.mode,
        authorized_writes=payload.authorized_writes,
        workspace=payload.workspace,
    )


@router.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ready",
        "orchestrator": "AutonomousOrchestrator",
        "single_entry_point": True,
        "path": "/api/v2/autonomous/run",
    }
