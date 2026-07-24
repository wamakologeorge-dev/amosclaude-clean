"""Canonical Pydantic API contracts for the Amosclaud platform.

These models describe data crossing the public API boundary. Persistent records
remain owned by ``database.models``; service implementations should map those
records to these contracts rather than creating competing JSON shapes.
"""

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
    """Shared lifecycle used by Agent, fixer, CI, and deployment responses."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    VERIFYING = "verifying"
    SUCCESS = "success"  # Backward-compatible public value.
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NEEDS_REVIEW = "needs_review"


class DeploymentStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class DeploymentEnvironment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class AgentMode(str, Enum):
    PLAN = "plan"
    BUILD = "build"
    TEST = "test"
    REVIEW = "review"
    FIX = "fix"
    DEPLOY = "deploy"
    MONITOR = "monitor"
    AUTONOMOUS_CHECK = "autonomous-check"


class VerificationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class BuildRequest(BaseModel):
    mode: BuildMode
    instructions: str | None = Field(default=None, description="Text instructions for the build")
    context: str | None = Field(default=None, description="Additional context or project details")
    repository_id: int | None = None
    branch: str | None = None
    model_id: str | None = None


class BuildResult(BaseModel):
    status: BuildStatus
    mode: BuildMode
    summary: str
    generated_plan: str | None = None
    generated_code: str | None = None
    error: str | None = None
    repository_id: int | None = None
    commit_sha: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    verification_id: str | None = None


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
    verification_id: str | None = None


class PipelineTrigger(BaseModel):
    trigger: str = Field(default="manual", min_length=1)
    repository_id: int | None = None
    pull_request_id: int | None = None
    issue_id: int | None = None
    branch: str | None = "main"
    commit_sha: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class PipelineResponse(BaseModel):
    id: str
    status: PipelineStatus
    trigger: str
    repository_id: int | None = None
    pull_request_id: int | None = None
    branch: str | None = None
    commit_sha: str | None = None
    verification_id: str | None = None
    verification_status: VerificationStatus | None = None
    changed_files: list[str] = Field(default_factory=list)
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
    deployment_profile_id: str | None = Field(
        default=None,
        description="Approved repository deployment profile selected by the server.",
    )
    deploy_command: str | None = Field(
        default=None,
        description="Legacy compatibility only; servers must not execute this value directly.",
        deprecated=True,
    )
    repository_id: int | None = None
    commit_sha: str | None = None
    pre_deploy_tests: bool = True
    auto_rollback: bool = True


class DeploymentResponse(BaseModel):
    id: str
    status: DeploymentStatus
    environment: str
    repository_id: int | None = None
    commit_sha: str | None = None
    verification_id: str | None = None
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
    repository_id: int | None = None
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
    repository_id: int | None = None
    status: PipelineStatus | None = None
    accepted_at: datetime | None = None


class AutonomousAgentProfile(BaseModel):
    name: str
    owner: str
    role: str
    mission: str
    mode: AgentMode | str
    home: str
    pipeline: str
    scope: list[str]
    directives: list[str]


class AutonomousAgentRunRequest(BaseModel):
    mode: AgentMode = AgentMode.AUTONOMOUS_CHECK
    objective: str | None = None
    repository_id: int | None = None
    pull_request_id: int | None = None
    issue_id: int | None = None
    branch: str | None = "main"
    commit_sha: str | None = None
    model_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AutonomousAgentRunResponse(BaseModel):
    accepted: bool
    run_id: str
    mode: AgentMode | str
    objective: str
    reply: str
    pipeline_id: str
    status: PipelineStatus
    repository_id: int | None = None
    pull_request_id: int | None = None
    commit_sha: str | None = None
    verification_id: str | None = None
    verification_status: VerificationStatus | None = None
    changed_files: list[str] = Field(default_factory=list)
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
    repository_id: int | None = None
    commit_sha: str | None = None
    verification_id: str | None = None
    download_url: str | None = None
    uploaded_at: datetime
    created_at: datetime
