# ---------------------------------------------------------------------------
# Pipeline logs and artifacts models
# ---------------------------------------------------------------------------
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


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
