"""API schemas for the single Autonomous orchestrator."""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class AutonomousTaskRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=8000)
    mode: Literal["plan", "build", "test", "review", "fix", "deploy", "monitor"] = "plan"
    authorized_writes: bool = False
    workspace: str = "."
    metadata: dict[str, Any] = Field(default_factory=dict)


class AutonomousTaskResponse(BaseModel):
    status: str
    objective: str
    plan: list[str]
    evidence: list[str]
    changed_files: list[str]
    checks: list[dict[str, Any]]
    duration_seconds: float
    blocker: str | None = None
