"""Pydantic models for Amosclaud AI."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

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


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


# ---------------------------------------------------------------------------
# Pipeline models
# ---------------------------------------------------------------------------

class PipelineTrigger(BaseModel):
    trigger: str = Field(..., description="Trigger type: push | pull_request | schedule | manual")
    branch: Optional[str] = None
    commit_sha: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class PipelineJob(BaseModel):
    id: str
    name: str
    status: PipelineStatus = PipelineStatus.PENDING
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    logs: List[str] = Field(default_factory=list)


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


# ---------------------------------------------------------------------------
# Deployment models
# ---------------------------------------------------------------------------

class DeploymentConfig(BaseModel):
    environment: Environment = Environment.DEVELOPMENT
    version: Optional[str] = None
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


# ---------------------------------------------------------------------------
# Database migration models
# ---------------------------------------------------------------------------

class DatabaseMigration(BaseModel):
    migration_name: str
    auto_backup: bool = True
    rollback_on_failure: bool = True


# ---------------------------------------------------------------------------
# Generic response models
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    timestamp: datetime


class ErrorResponse(BaseModel):
    detail: str
    code: Optional[int] = None
