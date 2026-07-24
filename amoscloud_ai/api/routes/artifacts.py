"""Pipeline artifacts routes."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from amoscloud_ai.logger import log
from amoscloud_ai.models import PipelineArtifactResponse

router = APIRouter(prefix="/artifacts", tags=["artifacts"])

# In-memory stores (replace with database and file storage in production)
_artifacts: dict[str, PipelineArtifactResponse] = {}
_artifact_files: dict[str, bytes] = {}


@router.get("", response_model=List[PipelineArtifactResponse], summary="List artifacts")
async def list_artifacts(
    pipeline_id: str = Query(..., description="Pipeline ID to filter artifacts"),
    job_id: Optional[str] = Query(None, description="Optional job ID to filter artifacts"),
) -> List[PipelineArtifactResponse]:
    """List artifacts for a pipeline, optionally filtered by job ID."""
    artifacts = [a for a in _artifacts.values() if a.pipeline_id == pipeline_id]
    if job_id:
        artifacts = [a for a in artifacts if a.job_id == job_id]
    return artifacts


@router.post("", response_model=PipelineArtifactResponse, status_code=201, summary="Upload artifact")
async def upload_artifact(
    pipeline_id: str = Form(..., description="Pipeline ID"),
    job_id: str = Form(..., description="Job ID"),
    artifact_name: str = Form(..., description="Name of the artifact file"),
    artifact_type: str = Form(..., description="Type of artifact (e.g., report, binary, log)"),
    file: UploadFile = File(..., description="Artifact file to upload"),
) -> PipelineArtifactResponse:
    """Upload an artifact for a pipeline job."""
    artifact_id = str(uuid.uuid4())
    content = await file.read()

    artifact = PipelineArtifactResponse(
        id=artifact_id,
        pipeline_id=pipeline_id,
        job_id=job_id,
        artifact_name=artifact_name,
        artifact_type=artifact_type,
        file_size=len(content),
        mime_type=file.content_type or "application/octet-stream",
        uploaded_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    _artifacts[artifact_id] = artifact
    _artifact_files[artifact_id] = content
    log.info(f"Uploaded artifact {artifact_id} ({artifact_name}) for pipeline {pipeline_id}")
    return artifact


@router.get("/{artifact_id}", response_model=PipelineArtifactResponse, summary="Get artifact metadata")
async def get_artifact(artifact_id: str) -> PipelineArtifactResponse:
    """Get metadata for an artifact."""
    artifact = _artifacts.get(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found")
    return artifact


@router.get("/{artifact_id}/download", summary="Download artifact file")
async def download_artifact(artifact_id: str):
    """Download the artifact file."""
    artifact = _artifacts.get(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found")

    content = _artifact_files.get(artifact_id)
    if not content:
        raise HTTPException(status_code=404, detail="Artifact file not found")

    return StreamingResponse(
        iter([content]),
        media_type=artifact.mime_type,
        headers={"Content-Disposition": f"attachment; filename={artifact.artifact_name}"},
    )


@router.delete("/{artifact_id}", status_code=204, summary="Delete artifact")
async def delete_artifact(artifact_id: str) -> None:
    """Delete an artifact and its file."""
    if artifact_id not in _artifacts:
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found")
    del _artifacts[artifact_id]
    if artifact_id in _artifact_files:
        del _artifact_files[artifact_id]
    log.info(f"Deleted artifact {artifact_id}")
