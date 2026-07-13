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
    repo_url: Optional[str] = None
    branch: str = "main"
    build_command: Optional[str] = None
    start_command: Optional[str] = None
    env_vars: dict[str, str] = Field(default_factory=dict)
    port: int = Field(default=8000, ge=1, le=65535)


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
    worker_id: Optional[str] = None
    logs: Optional[str] = None


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
    source: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CopilotDelegationResponse(BaseModel):
    accepted: bool
    task_id: str
    reply: str
    delegated_to: str
    created_at: datetime
