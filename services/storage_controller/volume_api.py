"""Authenticated provisioning routes for the private storage controller."""

from __future__ import annotations

import shutil
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

try:  # Package imports used by tests and installed modules.
    from .controller import _authorize, _enabled, _safe_mountpoint
    from .volume_provisioner import (
        VolumeProvisionError,
        expected_confirmation,
        provision_volume,
    )
except ImportError:  # Top-level imports used by the controller container.
    from controller import _authorize, _enabled, _safe_mountpoint
    from volume_provisioner import (
        VolumeProvisionError,
        expected_confirmation,
        provision_volume,
    )

router = APIRouter()


class ProvisionRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=100)
    provider: Literal["gcp", "aws"]
    size_gib: int = Field(default=20480, ge=10, le=65536)
    resource: dict[str, Any]
    mountpoint: str = Field(min_length=1, max_length=500)
    filesystem: Literal["ext4", "xfs"] = "ext4"
    filesystem_label: str = Field(
        default="amosclaud-data",
        min_length=1,
        max_length=16,
    )
    owner_uid: int = Field(default=1000, ge=0, le=65535)
    owner_gid: int = Field(default=1000, ge=0, le=65535)
    directory_mode: str = Field(default="2770", pattern=r"^[0-7]{3,4}$")
    persist_mount: bool = False
    benchmark_size_gib: int = Field(default=10, ge=0, le=100)
    confirmation: str = Field(min_length=16, max_length=500)
    dry_run: bool = False


@router.get("/provision-ready", dependencies=[Depends(_authorize)])
def provision_ready() -> dict[str, Any]:
    tools = [
        "blkid",
        "df",
        "findmnt",
        "fio",
        "lsblk",
        "mount",
        "partprobe",
        "sgdisk",
        "sync",
        "udevadm",
        "wipefs",
        "mkfs.ext4",
        "mkfs.xfs",
    ]
    missing = [
        name
        for name in tools
        if not shutil.which(name, path="/usr/sbin:/usr/bin:/sbin:/bin")
    ]
    return {
        "status": "ready" if _enabled() and not missing else "blocked",
        "enabled": _enabled(),
        "providers": ["gcp", "aws"],
        "maximum_size_gib": 65536,
        "twenty_tib_profile_gib": 20480,
        "supported_filesystems": ["ext4", "xfs"],
        "missing_tools": missing,
        "safety": {
            "new_blank_volume_only": True,
            "gpt_required": True,
            "root_device_protected": True,
            "existing_signatures_blocked": True,
            "world_writable_mount_blocked": True,
            "bounded_fio_validation": True,
        },
    }


@router.post("/v1/provision", dependencies=[Depends(_authorize)])
def provision(request: ProvisionRequest) -> dict[str, Any]:
    if not _enabled():
        raise HTTPException(status_code=503, detail="Storage controller is disabled")
    payload = request.model_dump()
    expected = expected_confirmation(payload)
    if request.confirmation != expected:
        raise HTTPException(
            status_code=422,
            detail=f"Confirmation must exactly equal: {expected}",
        )
    mountpoint = _safe_mountpoint(request.mountpoint)
    try:
        result = provision_volume(payload, mountpoint=mountpoint)
    except VolumeProvisionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Provisioning failed safely: {type(exc).__name__}",
        ) from exc
    cloud = result.get("cloud") or {}
    return {
        "operation_id": f"provision_{request.request_id}",
        "request_id": request.request_id,
        "status": "planned" if request.dry_run else "completed",
        **result,
        "safety": {
            "cloud_resource_created_for_this_request": bool(cloud.get("created")),
            "blank_device_and_root_disk_checks_required": True,
            "gpt_partition_table_required": True,
            "arbitrary_commands_allowed": False,
            "runs_inside_developer_workspace": False,
            "world_writable_mount": False,
            "validation_file_removed": True,
        },
    }
