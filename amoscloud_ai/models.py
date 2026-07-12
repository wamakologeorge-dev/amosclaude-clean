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
    task: str
    source: Optional[str] = None
    reply: str
    copilot_role: str
    delegation_target: str
    scope: list[str]
    pipeline_id: Optional[str] = None
    status: Optional[PipelineStatus] = None
    accepted_at: Optional[datetime] = None


class ChatRequest(BaseModel):
    """A message from the web or Android Amosclaud client."""

    message: str = Field(..., min_length=1, max_length=12000)
    session_id: Optional[str] = Field(default=None, max_length=128)
    start_pr_task: bool = False
    base_branch: str = Field(default="main", pattern=r"^[A-Za-z0-9._/-]+$")


class ChatResponse(BaseModel):
    """A response that both first-party clients can consume."""

    reply: str
    session_id: str
    timestamp: datetime
    provider: str
    task_id: Optional[str] = None
    task_status: Optional[str] = None
    task_url: Optional[str] = None


class AgentCapabilityResponse(BaseModel):
    name: str
    version: str
    capabilities: list[str]
    repository_scope: str
    execution_mode: str



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


class RepositoryTaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RepositoryTaskRequest(BaseModel):
    """An authenticated owner command for the configured Amosclaud repository."""

    objective: str = Field(..., min_length=3, max_length=12000)
    base_branch: str = Field(default="main", pattern=r"^[A-Za-z0-9._/-]+$")


class RepositoryTaskResponse(BaseModel):
    task_id: str
    status: RepositoryTaskStatus
    objective: str
    branch: str
    message: str
    created_at: datetime
    updated_at: datetime
    pull_request_url: Optional[str] = None
    logs: list[str] = Field(default_factory=list)
