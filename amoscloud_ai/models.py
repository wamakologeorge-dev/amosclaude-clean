"""Pydantic models for the Amosclaud AI platform."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class BuildMode(str, Enum):
    PHOTO = "photo"
    INSTRUCTIONS = "instructions"


class BuildStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class BuildRequest(BaseModel):
    mode: BuildMode
    instructions: Optional[str] = Field(default=None, description="Text instructions for the build")
    context: Optional[str] = Field(default=None, description="Additional context or project details")


class BuildResult(BaseModel):
    status: BuildStatus
    mode: BuildMode
    summary: str
    generated_plan: Optional[str] = None
    generated_code: Optional[str] = None
    error: Optional[str] = None


class DatabaseMigration(BaseModel):
    migration_name: str
    auto_backup: bool = True
    rollback_on_failure: bool = True


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    timestamp: datetime


class PipelineStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PipelineTrigger(BaseModel):
    trigger: str = "manual"
    branch: str = "main"
    commit_sha: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)


class PipelineJob(BaseModel):
    id: str
    name: str
    status: PipelineStatus = PipelineStatus.PENDING
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    logs: list[str] = Field(default_factory=list)


class PipelineResponse(BaseModel):
    id: str
    status: PipelineStatus
    trigger: str
    branch: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    message: Optional[str] = None
    copilot_reply: Optional[str] = None
    copilot_role: Optional[str] = None
    delegation_target: Optional[str] = None
    jobs: list[PipelineJob] = Field(default_factory=list)


class DeploymentEnvironment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class DeploymentStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class DeploymentConfig(BaseModel):
    version: str = Field(default="latest", min_length=1)
    environment: DeploymentEnvironment = DeploymentEnvironment.DEVELOPMENT
    deploy_command: Optional[str] = None
    pre_deploy_tests: bool = True
    auto_rollback: bool = True


class DeploymentResponse(BaseModel):
    id: str
    status: DeploymentStatus
    environment: str
    version: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    message: Optional[str] = None
    copilot_reply: Optional[str] = None
    copilot_role: Optional[str] = None
    delegation_target: Optional[str] = None


class AutonomousAgentProfile(BaseModel):
    name: str
    owner: str
    role: str
    mission: str
    mode: str
    home: str
    pipeline: str
    scope: list[str] = Field(default_factory=list)
    directives: list[str] = Field(default_factory=list)


class AutonomousAgentRunRequest(BaseModel):
    mode: str = "autonomous-check"
    objective: Optional[str] = None
    branch: str = "main"
    metadata: dict[str, Any] = Field(default_factory=dict)


class AutonomousCheckResult(BaseModel):
    name: str
    status: str
    summary: str
    details: list[str] = Field(default_factory=list)


class AutonomousAgentRunResponse(BaseModel):
    accepted: bool
    run_id: str
    mode: str
    objective: str
    reply: str
    pipeline_id: str
    status: PipelineStatus
    started_at: datetime
    checks: list[AutonomousCheckResult] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)


class PipelineLogCreate(BaseModel):
    pipeline_id: str = Field(..., description="Pipeline ID")
    job_id: str = Field(..., description="Job ID")
    log_level: str = Field(default="INFO", description="Log level (DEBUG, INFO, WARNING, ERROR)")
    message: str = Field(..., description="Log message")


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
