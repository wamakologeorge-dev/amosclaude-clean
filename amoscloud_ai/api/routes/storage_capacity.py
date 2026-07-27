"""Administrator-only workspace storage capacity control plane."""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from amoscloud_ai import storage_capacity
from amoscloud_ai.api.routes import admin

router = APIRouter(prefix="/admin/storage-capacity", tags=["administration", "storage-capacity"])


class ResizeJobCreate(BaseModel):
    provider: Literal["gcp", "aws"]
    target_size_gib: int = Field(ge=10, le=65536)
    mountpoint: str = Field(min_length=1, max_length=500)
    expected_device: str | None = Field(default=None, max_length=300)
    snapshot_required: bool = True
    expand_filesystem: bool = True
    dry_run: bool = False
    confirmation: str = Field(min_length=8, max_length=300)

    gcp_project_id: str | None = Field(default=None, max_length=200)
    gcp_disk_link: str | None = Field(default=None, max_length=1_000)
    aws_region: str | None = Field(default=None, max_length=100)
    aws_volume_id: str | None = Field(default=None, max_length=100)


def _max_size_gib() -> int:
    try:
        configured = int(os.getenv("AMOSCLAUD_STORAGE_MAX_SIZE_GIB", "2048"))
    except ValueError:
        configured = 2048
    return max(10, min(configured, 65536))


def _safe_mountpoint(value: str) -> str:
    if "\x00" in value:
        raise HTTPException(status_code=422, detail="Mountpoint is invalid")
    path = Path(value).expanduser()
    if not path.is_absolute() or ".." in path.parts:
        raise HTTPException(status_code=422, detail="Mountpoint must be an absolute managed path")
    return str(path)


def _resource(body: ResizeJobCreate) -> tuple[dict, str]:
    if body.provider == "gcp":
        project = str(body.gcp_project_id or "").strip()
        disk_link = str(body.gcp_disk_link or "").strip().rstrip("/")
        if not project or not disk_link:
            raise HTTPException(
                status_code=422,
                detail="GCP resizing requires gcp_project_id and gcp_disk_link",
            )
        if not re.fullmatch(r"[A-Za-z0-9:_-]{3,200}", project):
            raise HTTPException(status_code=422, detail="GCP project ID is invalid")
        return {"project_id": project, "disk_link": disk_link}, disk_link

    region = str(body.aws_region or "").strip()
    volume_id = str(body.aws_volume_id or "").strip()
    if not region or not volume_id:
        raise HTTPException(
            status_code=422,
            detail="AWS resizing requires aws_region and aws_volume_id",
        )
    if not re.fullmatch(r"[a-z]{2}(?:-gov)?-[a-z]+-\d", region):
        raise HTTPException(status_code=422, detail="AWS region is invalid")
    if not re.fullmatch(r"vol-[0-9a-fA-F]{8,32}", volume_id):
        raise HTTPException(status_code=422, detail="AWS volume ID is invalid")
    return {"region": region, "volume_id": volume_id}, volume_id


def _confirmation(provider: str, resource_name: str, size_gib: int) -> str:
    return f"RESIZE {provider.upper()} {resource_name} TO {size_gib}GiB"


@router.get("/controller")
def storage_controller_status(
    administrator: sqlite3.Row = Depends(admin._admin_user),
) -> dict:
    del administrator
    return {
        **storage_capacity.controller_health(),
        "maximum_size_gib": _max_size_gib(),
        "snapshot_required_for_real_resize": True,
        "filesystem_expansion_location": "privileged storage host, never a developer sandbox",
    }


@router.post("/jobs", status_code=202)
def create_resize_job(
    body: ResizeJobCreate,
    administrator: sqlite3.Row = Depends(admin._admin_user),
) -> dict:
    resource, resource_name = _resource(body)
    maximum = _max_size_gib()
    if body.target_size_gib > maximum:
        raise HTTPException(
            status_code=422,
            detail=f"Requested size exceeds the configured {maximum} GiB limit",
        )
    if not body.snapshot_required and not body.dry_run:
        raise HTTPException(
            status_code=422,
            detail="A pre-resize snapshot is mandatory for a real storage resize",
        )
    expected = _confirmation(body.provider, resource_name, body.target_size_gib)
    if body.confirmation.strip() != expected:
        raise HTTPException(
            status_code=422,
            detail=f"Confirmation must exactly equal: {expected}",
        )

    job = storage_capacity.create_job(
        requested_by=int(administrator["id"]),
        provider=body.provider,
        resource=resource,
        target_size_gib=body.target_size_gib,
        mountpoint=_safe_mountpoint(body.mountpoint),
        expected_device=body.expected_device,
        snapshot_required=body.snapshot_required,
        expand_filesystem=body.expand_filesystem,
        dry_run=body.dry_run,
    )
    try:
        storage_capacity.dispatch_job(job["id"])
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "The resize job was saved but the background worker is unavailable. "
                f"Job ID: {job['id']} ({type(exc).__name__})"
            ),
        ) from exc
    return job


@router.get("/jobs")
def resize_jobs(
    limit: int = Query(default=100, ge=1, le=500),
    administrator: sqlite3.Row = Depends(admin._admin_user),
) -> list[dict]:
    del administrator
    return storage_capacity.list_jobs(limit)


@router.get("/jobs/{job_id}")
def resize_job(
    job_id: str,
    administrator: sqlite3.Row = Depends(admin._admin_user),
) -> dict:
    del administrator
    try:
        return storage_capacity.get_job(job_id)
    except storage_capacity.StorageCapacityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
