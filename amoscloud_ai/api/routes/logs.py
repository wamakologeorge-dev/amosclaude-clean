"""Pipeline logs routes."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from amoscloud_ai.logger import log
from amoscloud_ai.models import PipelineLogCreate, PipelineLogResponse

router = APIRouter(prefix="/logs", tags=["logs"])

# In-memory store (replace with database in production)
_logs: dict[str, PipelineLogResponse] = {}


@router.get("", response_model=List[PipelineLogResponse], summary="List pipeline logs")
async def list_logs(
    pipeline_id: str = Query(..., description="Pipeline ID to filter logs"),
    job_id: Optional[str] = Query(None, description="Optional job ID to filter logs"),
    limit: int = Query(100, ge=1, le=1000, description="Max logs to return"),
) -> List[PipelineLogResponse]:
    """List logs for a pipeline, optionally filtered by job ID."""
    logs = [log for log in _logs.values() if log.pipeline_id == pipeline_id]
    if job_id:
        logs = [log for log in logs if log.job_id == job_id]
    return logs[-limit:]


@router.post("", response_model=PipelineLogResponse, status_code=201, summary="Create a log entry")
async def create_log(body: PipelineLogCreate) -> PipelineLogResponse:
    """Create a new log entry for a pipeline job."""
    log_id = str(uuid.uuid4())
    log_entry = PipelineLogResponse(
        id=log_id,
        pipeline_id=body.pipeline_id,
        job_id=body.job_id,
        log_level=body.log_level,
        message=body.message,
        timestamp=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    _logs[log_id] = log_entry
    log.info(f"Created log {log_id} for pipeline {body.pipeline_id}")
    return log_entry


@router.delete("/{pipeline_id}", status_code=204, summary="Delete all logs for a pipeline")
async def delete_logs(pipeline_id: str) -> None:
    """Delete all logs associated with a pipeline."""
    keys_to_delete = [k for k, v in _logs.items() if v.pipeline_id == pipeline_id]
    for key in keys_to_delete:
        del _logs[key]
    log.info(f"Deleted {len(keys_to_delete)} logs for pipeline {pipeline_id}")
