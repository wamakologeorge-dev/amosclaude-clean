"""Pydantic models for Amoscloud AI"""

from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


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


class DeploymentConfig(BaseModel):
    environment: str
    deploy_command: Optional[str] = None
    pre_deploy_tests: bool = True
    auto_rollback: bool = True
