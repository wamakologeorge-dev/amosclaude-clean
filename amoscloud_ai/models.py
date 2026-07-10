"""Pydantic models for Amosclaud AI."""
"""Pydantic models for Amoscloud AI"""

from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
from datetime import datetime


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

class PipelineResponse(BaseModel):
    id: str
    status: PipelineStatus
    trigger: str
    branch: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    message: Optional[str] = None
    copilot_reply: Optional[str] = None
    copilot_role: Optional[str] = None
    delegation_target: Optional[str] = None
    jobs: List[PipelineJob] = Field(default_factory=list)

class DatabaseMigration(BaseModel):
    migration_name: str
    auto_backup: bool = True
    rollback_on_failure: bool = True


class DeploymentConfig(BaseModel):
    environment: str
    deploy_command: Optional[str] = None
    pre_deploy_tests: bool = True
    auto_rollback: bool = True


class DeploymentResponse(BaseModel):
    id: str
    status: DeploymentStatus
    environment: str
    version: Optional[str] = None
    started_at: Optional[datetime] = None
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
    scope: List[str]
    directives: List[str]


class CopilotDelegationRequest(BaseModel):
    task: str = Field(..., min_length=1, description="Work to delegate to Amosclaud Copilot")
    source: Optional[str] = Field(default=None, description="Caller, channel, or request source")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CopilotDelegationResponse(BaseModel):
    accepted: bool
    task: str
    source: Optional[str] = None
    reply: str
    copilot_role: str
    delegation_target: str
    scope: List[str]
    pipeline_id: Optional[str] = None
    status: Optional[PipelineStatus] = None
    accepted_at: Optional[datetime] = None


class AutonomousAgentProfile(BaseModel):
    name: str
    owner: str
    role: str
    mission: str
    mode: str
    home: str
    pipeline: str
    scope: List[str]
    directives: List[str]


class AutonomousAgentRunRequest(BaseModel):
    mode: str = Field(default="autonomous-check", description="autonomous-check | build | deploy | monitor")
    objective: Optional[str] = Field(default=None, description="Optional target for this autonomous run")
    branch: Optional[str] = Field(default="main", description="Branch to run against")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AutonomousAgentRunResponse(BaseModel):
    accepted: bool
    run_id: str
    mode: str
    objective: str
    reply: str
    pipeline_id: str
    status: PipelineStatus
    started_at: datetime
    checks: List[Dict[str, Any]] = Field(default_factory=list)
    logs: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pipeline logs and artifacts models
# ---------------------------------------------------------------------------

class PipelineStatus(str, Enum):
    """Pipeline execution status."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


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
