"""API for Agent Operations Controller and Mission Control."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.agent.actions import run_autonomous
from src.agent.operations_controller import AgentOperationsController

router = APIRouter(prefix="/api/v2/agent-operations", tags=["agent-operations"])
controller = AgentOperationsController(run_autonomous)


class JobRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=8000)
    mode: str = "plan"
    authorized_writes: bool = False
    workspace: str = "."


@router.post("/jobs")
def create_job(payload: JobRequest) -> dict:
    return controller.submit(
        objective=payload.objective,
        mode=payload.mode,
        authorized_writes=payload.authorized_writes,
        workspace=payload.workspace,
    )


@router.get("/jobs")
def list_jobs(limit: int = 50) -> list[dict]:
    return controller.list_jobs(limit)


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = controller.get(job_id)
    if job.get("status") == "missing":
        raise HTTPException(status_code=404, detail="Agent job not found")
    return job


@router.get("/mission-control")
def mission_control() -> dict:
    jobs = controller.list_jobs(100)
    active = [job for job in jobs if job["status"] in {"queued", "running", "waiting_for_approval"}]
    failed = [job for job in jobs if job["status"] in {"failed", "blocked"}]
    completed = [job for job in jobs if job["status"] == "completed"]
    return {
        "status": "ready",
        "active_jobs": len(active),
        "completed_jobs": len(completed),
        "failed_or_blocked_jobs": len(failed),
        "jobs": jobs,
        "truthful_states": ["completed", "partially_completed", "blocked", "failed", "waiting_for_approval"],
    }
