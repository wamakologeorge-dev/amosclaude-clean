"""Administrator-only workspace storage capacity control plane."""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from amoscloud_ai import storage_capacity, storage_provisioning
from amoscloud_ai.api.routes import admin

router = APIRouter(
    prefix="/admin/storage-capacity",
    tags=["administration", "storage-capacity"],
)


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


class ProvisionJobCreate(BaseModel):
    provider: Literal["gcp", "aws"]
    size_gib: int = Field(default=20480, ge=10, le=65536)
    mountpoint: str = Field(
        default="/mnt/amosclaud-volumes/amosclaud-20tb",
        min_length=1,
        max_length=500,
    )
    filesystem: Literal["ext4", "xfs"] = "ext4"
    filesystem_label: str = Field(
        default="amosclaud-data",
        min_length=1,
        max_length=16,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    owner_uid: int = Field(default=1000, ge=0, le=65535)
    owner_gid: int = Field(default=1000, ge=0, le=65535)
    directory_mode: str = Field(default="2770", pattern=r"^[0-7]{3,4}$")
    persist_mount: bool = False
    benchmark_size_gib: int = Field(default=10, ge=0, le=100)
    dry_run: bool = False
    confirmation: str = Field(min_length=16, max_length=500)

    gcp_project_id: str | None = Field(default=None, max_length=200)
    gcp_zone: str | None = Field(default=None, max_length=100)
    gcp_instance_name: str | None = Field(default=None, max_length=100)
    gcp_disk_name: str | None = Field(default=None, max_length=100)
    gcp_device_name: str | None = Field(default=None, max_length=100)
    gcp_disk_type: Literal["pd-balanced", "pd-ssd", "pd-standard"] = (
        "pd-balanced"
    )

    aws_region: str | None = Field(default=None, max_length=100)
    aws_availability_zone: str | None = Field(default=None, max_length=100)
    aws_instance_id: str | None = Field(default=None, max_length=100)
    aws_volume_name: str | None = Field(default=None, max_length=128)
    aws_volume_type: Literal["gp2", "gp3", "io1", "io2", "st1", "sc1"] = (
        "gp3"
    )
    aws_device_name: str = Field(default="/dev/sdf", max_length=20)
    aws_iops: int | None = Field(default=None, ge=100, le=256000)
    aws_throughput_mibps: int | None = Field(default=None, ge=125, le=2000)


def _max_size_gib() -> int:
    try:
        configured = int(os.getenv("AMOSCLAUD_STORAGE_MAX_SIZE_GIB", "20480"))
    except ValueError:
        configured = 20480
    return max(10, min(configured, 65536))


_MOUNTPOINT_PATTERN = re.compile(r"^/[A-Za-z0-9._/\-]+$")


def _safe_mountpoint(value: str) -> str:
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail="Mountpoint is invalid")
    candidate = value.strip()
    if not candidate or "\x00" in candidate:
        raise HTTPException(status_code=422, detail="Mountpoint is invalid")
    if not _MOUNTPOINT_PATTERN.fullmatch(candidate):
        raise HTTPException(
            status_code=422,
            detail="Mountpoint contains unsupported characters",
        )

    path = Path(os.path.realpath(os.path.expanduser(candidate)))
    if not path.is_absolute() or ".." in path.parts:
        raise HTTPException(
            status_code=422,
            detail="Mountpoint must be an absolute managed path",
        )

    allowed_roots_raw = os.getenv(
        "AMOSCLOUD_STORAGE_ALLOWED_MOUNT_ROOTS",
        "/mnt/amosclaud-volumes,/mnt,/media",
    )
    allowed_roots = [
        Path(os.path.realpath(os.path.expanduser(part.strip())))
        for part in allowed_roots_raw.split(",")
        if part.strip()
    ]

    for root in allowed_roots:
        try:
            path.relative_to(root)
            return str(path)
        except ValueError:
            continue

    raise HTTPException(
        status_code=422,
        detail="Mountpoint must be within configured managed roots",
    )


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


def _provision_resource(body: ProvisionJobCreate) -> tuple[dict, str]:
    if body.provider == "gcp":
        project = str(body.gcp_project_id or "").strip()
        zone = str(body.gcp_zone or "").strip()
        instance = str(body.gcp_instance_name or "").strip()
        disk_name = str(body.gcp_disk_name or "").strip()
        device_name = str(body.gcp_device_name or disk_name).strip()
        if not all((project, zone, instance, disk_name, device_name)):
            raise HTTPException(
                status_code=422,
                detail=(
                    "GCP provisioning requires project, zone, instance, disk name, "
                    "and device name"
                ),
            )
        if not re.fullmatch(r"[A-Za-z0-9:_-]{3,200}", project):
            raise HTTPException(status_code=422, detail="GCP project ID is invalid")
        name_pattern = r"[a-z]([-a-z0-9]{0,61}[a-z0-9])?"
        if not re.fullmatch(name_pattern, disk_name) or not re.fullmatch(
            name_pattern,
            device_name,
        ):
            raise HTTPException(
                status_code=422,
                detail="GCP disk and device names are invalid",
            )
        return (
            {
                "project_id": project,
                "zone": zone,
                "instance_name": instance,
                "disk_name": disk_name,
                "device_name": device_name,
                "disk_type": body.gcp_disk_type,
            },
            disk_name,
        )

    region = str(body.aws_region or "").strip()
    zone = str(body.aws_availability_zone or "").strip()
    instance = str(body.aws_instance_id or "").strip()
    volume_name = str(body.aws_volume_name or "").strip()
    if not all((region, zone, instance, volume_name)):
        raise HTTPException(
            status_code=422,
            detail=(
                "AWS provisioning requires region, availability zone, instance ID, "
                "and volume name"
            ),
        )
    if not re.fullmatch(r"[a-z]{2}(?:-gov)?-[a-z]+-\d", region):
        raise HTTPException(status_code=422, detail="AWS region is invalid")
    if not zone.startswith(region) or len(zone) > 32:
        raise HTTPException(status_code=422, detail="AWS availability zone is invalid")
    if not re.fullmatch(r"i-[0-9a-fA-F]{8,32}", instance):
        raise HTTPException(status_code=422, detail="AWS instance ID is invalid")
    if not re.fullmatch(r"[A-Za-z0-9_.:/=+@-]{1,128}", volume_name):
        raise HTTPException(status_code=422, detail="AWS volume name is invalid")
    if not re.fullmatch(r"/dev/sd[f-p]", body.aws_device_name):
        raise HTTPException(
            status_code=422,
            detail="AWS device name must be between /dev/sdf and /dev/sdp",
        )
    return (
        {
            "region": region,
            "availability_zone": zone,
            "instance_id": instance,
            "volume_name": volume_name,
            "volume_type": body.aws_volume_type,
            "device_name": body.aws_device_name,
            "iops": body.aws_iops,
            "throughput_mibps": body.aws_throughput_mibps,
        },
        volume_name,
    )


def _confirmation(provider: str, resource_name: str, size_gib: int) -> str:
    return f"RESIZE {provider.upper()} {resource_name} TO {size_gib}GiB"


def _provision_confirmation(
    provider: str,
    resource_name: str,
    size_gib: int,
    filesystem: str,
) -> str:
    return (
        f"PROVISION {provider.upper()} {resource_name} {size_gib}GiB "
        f"AND FORMAT {filesystem.upper()}"
    )


def _provision_controller_health() -> dict:
    try:
        response = httpx.get(
            f"{storage_capacity._controller_url()}/provision-ready",
            headers={
                "Authorization": f"Bearer {storage_capacity._controller_token()}"
            },
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
        return {
            "reachable": True,
            "status": payload.get("status") or "unknown",
            "missing_tools": payload.get("missing_tools", []),
            "supported_filesystems": payload.get("supported_filesystems", []),
            "twenty_tib_profile_gib": payload.get("twenty_tib_profile_gib"),
        }
    except Exception as exc:
        return {
            "reachable": False,
            "status": "unavailable",
            "detail": f"Provisioning controller unavailable: {type(exc).__name__}",
            "missing_tools": [],
            "supported_filesystems": [],
        }


@router.get("/controller")
def storage_controller_status(
    administrator: sqlite3.Row = Depends(admin._admin_user),
) -> dict:
    del administrator
    return {
        **storage_capacity.controller_health(),
        "provisioning_controller": _provision_controller_health(),
        "maximum_size_gib": _max_size_gib(),
        "twenty_tib_profile_gib": 20480,
        "new_volume_provisioning": True,
        "snapshot_required_for_real_resize": True,
        "filesystem_expansion_location": (
            "privileged storage host, never a developer sandbox"
        ),
        "new_volume_safety": {
            "new_blank_volume_only": True,
            "gpt_required_above_2_tib": True,
            "root_disk_protected": True,
            "world_writable_mount_blocked": True,
            "bounded_fio_validation": True,
        },
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


@router.post("/provision-jobs", status_code=202)
def create_provision_job(
    body: ProvisionJobCreate,
    administrator: sqlite3.Row = Depends(admin._admin_user),
) -> dict:
    maximum = _max_size_gib()
    if body.size_gib > maximum:
        raise HTTPException(
            status_code=422,
            detail=f"Requested size exceeds the configured {maximum} GiB limit",
        )
    resource, resource_name = _provision_resource(body)
    expected = _provision_confirmation(
        body.provider,
        resource_name,
        body.size_gib,
        body.filesystem,
    )
    if body.confirmation.strip() != expected:
        raise HTTPException(
            status_code=422,
            detail=f"Confirmation must exactly equal: {expected}",
        )

    job = storage_provisioning.create_job(
        requested_by=int(administrator["id"]),
        provider=body.provider,
        resource=resource,
        size_gib=body.size_gib,
        mountpoint=_safe_mountpoint(body.mountpoint),
        filesystem=body.filesystem,
        filesystem_label=body.filesystem_label,
        owner_uid=body.owner_uid,
        owner_gid=body.owner_gid,
        directory_mode=body.directory_mode,
        persist_mount=body.persist_mount,
        benchmark_size_gib=body.benchmark_size_gib,
        confirmation=expected,
        dry_run=body.dry_run,
    )
    try:
        storage_provisioning.dispatch_job(job["id"])
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "The provisioning job was saved but the background worker is "
                f"unavailable. Job ID: {job['id']} ({type(exc).__name__})"
            ),
        ) from exc
    return job


@router.get("/provision-jobs")
def provision_jobs(
    limit: int = Query(default=100, ge=1, le=500),
    administrator: sqlite3.Row = Depends(admin._admin_user),
) -> list[dict]:
    del administrator
    return storage_provisioning.list_jobs(limit)


@router.get("/provision-jobs/{job_id}")
def provision_job(
    job_id: str,
    administrator: sqlite3.Row = Depends(admin._admin_user),
) -> dict:
    del administrator
    try:
        return storage_provisioning.get_job(job_id)
    except storage_provisioning.StorageProvisioningError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
