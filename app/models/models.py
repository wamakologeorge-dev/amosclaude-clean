"""Pydantic models for the Amosclaud AI API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class BuildMode(str, Enum):
    PHOTO = "photo"
    INSTRUCTIONS = "instructions"


class BuildStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class PipelineStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeploymentStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class DeploymentEnvironment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class BuildRequest(BaseModel):
    mode: BuildMode
    instructions: str | None = Field(default=None, description="Text instructions for the build")
    context: str | None = Field(default=None, description="Additional context or project details")


class BuildResult(BaseModel):
    status: BuildStatus
    mode: BuildMode
    summary: str
    generated_plan: str | None = None
    generated_code: str | None = None
    error: str | None = None


class DatabaseMigration(BaseModel):
    migration_name: str
    auto_backup: bool = True
    rollback_on_failure: bool = True


class PipelineJob(BaseModel):
    id: str
    name: str
    status: PipelineStatus = PipelineStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    logs: list[str] = Field(default_factory=list)


class PipelineTrigger(BaseModel):
    trigger: str = Field(default="manual", min_length=1)
    branch: str | None = "main"
    commit_sha: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class PipelineResponse(BaseModel):
    id: str
    status: PipelineStatus
    trigger: str
    branch: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    message: str | None = None
    copilot_reply: str | None = None
    copilot_role: str | None = None
    delegation_target: str | None = None
    jobs: list[PipelineJob] = Field(default_factory=list)


class DeploymentConfig(BaseModel):
    environment: DeploymentEnvironment = DeploymentEnvironment.DEVELOPMENT
    version: str | None = None
    deploy_command: str | None = None
    pre_deploy_tests: bool = True
    auto_rollback: bool = True


class DeploymentResponse(BaseModel):
    id: str
    status: DeploymentStatus
    environment: str
    version: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    message: str | None = None
    copilot_reply: str | None = None
    copilot_role: str | None = None
    delegation_target: str | None = None


class CopilotProfile(BaseModel):
    name: str
    owner: str
    role: str
    mission: str
    home: str
    pipeline: str
    scope: list[str]
    directives: list[str]


class CopilotDelegationRequest(BaseModel):
    task: str = Field(..., min_length=1)
    source: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CopilotDelegationResponse(BaseModel):
    accepted: bool
    task: str
    source: str | None = None
    reply: str
    copilot_role: str
    delegation_target: str
    scope: list[str]
    pipeline_id: str | None = None
    status: PipelineStatus | None = None
    accepted_at: datetime | None = None


class AutonomousAgentProfile(BaseModel):
    name: str
    owner: str
    role: str
    mission: str
    mode: str
    home: str
    pipeline: str
    scope: list[str]
    directives: list[str]


class AutonomousAgentRunRequest(BaseModel):
    mode: str = "autonomous-check"
    objective: str | None = None
    branch: str | None = "main"
    metadata: dict[str, Any] = Field(default_factory=dict)


class AutonomousAgentRunResponse(BaseModel):
    accepted: bool
    run_id: str
    mode: str
    objective: str
    reply: str
    pipeline_id: str
    status: PipelineStatus
    started_at: datetime
    checks: list[dict[str, Any]] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)


class PipelineLogCreate(BaseModel):
    pipeline_id: str
    job_id: str
    log_level: str = "INFO"
    message: str


class PipelineLogResponse(BaseModel):
    id: str
    pipeline_id: str
    job_id: str
    log_level: str
    message: str
    timestamp: datetime
    created_at: datetime


class PipelineArtifactResponse(BaseModel):
    id: str
    pipeline_id: str
    job_id: str
    artifact_name: str
    artifact_type: str
    file_size: int
    mime_type: str
    uploaded_at: datetime
    created_at: datetime
