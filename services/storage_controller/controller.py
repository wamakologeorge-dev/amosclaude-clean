"""Internal privileged storage controller for Amosclaud workspace volumes.

This service must run on the storage host or an equivalent privileged
infrastructure node. It must never be exposed to users or executed inside a
user workspace. It supports only cloud disk growth and ext4/XFS expansion; no
arbitrary command execution is accepted.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Amosclaud Storage Controller", version="1")

_GCP_DISK = re.compile(
    r"(?:https://www\.googleapis\.com/compute/v1/)?projects/(?P<project>[A-Za-z0-9:_-]+)/"
    r"(?P<scope>zones|regions)/(?P<location>[A-Za-z0-9_-]+)/disks/(?P<disk>[A-Za-z0-9_-]+)$"
)
_AWS_VOLUME = re.compile(r"^vol-[0-9a-fA-F]{8,32}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,100}$")


class ResizeRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=100)
    provider: Literal["gcp", "aws"]
    target_size_gib: int = Field(ge=10, le=65536)
    resource: dict[str, Any]
    mountpoint: str = Field(min_length=1, max_length=500)
    expected_device: str | None = Field(default=None, max_length=300)
    snapshot_required: bool = True
    expand_filesystem: bool = True
    dry_run: bool = False


class FilesystemPlan(BaseModel):
    mountpoint: str
    source: str
    fstype: str
    parent_device: str | None
    partition_number: int | None


def _token() -> str:
    value = os.getenv("AMOSCLAUD_STORAGE_CONTROLLER_TOKEN", "").strip()
    if len(value) < 32:
        raise RuntimeError("AMOSCLAUD_STORAGE_CONTROLLER_TOKEN is missing or too short")
    return value


def _authorize(authorization: str | None = Header(default=None)) -> None:
    expected = _token()
    supplied = ""
    if authorization and authorization.startswith("Bearer "):
        supplied = authorization.removeprefix("Bearer ").strip()
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Storage controller authentication failed")


def _enabled() -> bool:
    return os.getenv("AMOSCLAUD_STORAGE_CONTROLLER_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _allowed_mount_roots() -> tuple[Path, ...]:
    raw = os.getenv(
        "AMOSCLAUD_STORAGE_ALLOWED_MOUNTS",
        "/var/lib/amosclaud/repositories,/data/repositories",
    )
    roots = []
    for item in raw.split(","):
        cleaned = item.strip()
        if cleaned:
            roots.append(Path(cleaned).resolve())
    if not roots:
        raise RuntimeError("AMOSCLAUD_STORAGE_ALLOWED_MOUNTS must contain at least one root")
    return tuple(dict.fromkeys(roots))


def _safe_mountpoint(value: str) -> Path:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="mountpoint is required")
    if "\x00" in cleaned:
        raise HTTPException(status_code=422, detail="mountpoint contains invalid characters")
    if not os.path.isabs(cleaned):
        raise HTTPException(status_code=422, detail="mountpoint must be an absolute path")

    candidate = Path(cleaned).expanduser().resolve(strict=False)
    for root in _allowed_mount_roots():
        try:
            candidate.relative_to(root)
            return candidate
        except ValueError:
            continue
    raise HTTPException(status_code=422, detail="Mountpoint is outside the storage-controller allowlist")


def _run(command: list[str], *, timeout: int = 120) -> str:
    if not command or not Path(command[0]).is_absolute():
        raise RuntimeError("Storage controller commands must use absolute executable paths")
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={
            "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        },
    )
    output = (completed.stdout + "\n" + completed.stderr).strip()
    if completed.returncode != 0:
        raise RuntimeError(
            f"{Path(command[0]).name} failed with exit code {completed.returncode}: {output[:1000]}"
        )
    return output


def _which(name: str) -> str:
    path = shutil.which(name, path="/usr/sbin:/usr/bin:/sbin:/bin")
    if not path:
        raise RuntimeError(f"Required storage tool is unavailable: {name}")
    return path


def _findmnt(mountpoint: Path) -> dict[str, Any]:
    output = _run(
        [
            _which("findmnt"),
            "--json",
            "--target",
            str(mountpoint),
            "--output",
            "SOURCE,FSTYPE,TARGET",
        ]
    )
    payload = json.loads(output)
    filesystems = payload.get("filesystems") or []
    if len(filesystems) != 1:
        raise RuntimeError("Unable to resolve exactly one filesystem for the mountpoint")
    return filesystems[0]


def _lsblk_value(device: str, column: str) -> str:
    return _run([_which("lsblk"), "--noheadings", "--output", column, device]).strip()


def filesystem_plan(mountpoint: Path, expected_device: str | None = None) -> FilesystemPlan:
    info = _findmnt(mountpoint)
    source = str(info.get("source") or "").strip()
    fstype = str(info.get("fstype") or "").strip().lower()
    target = Path(str(info.get("target") or mountpoint)).resolve()
    if target != mountpoint:
        raise RuntimeError("Resolved filesystem target does not match the approved mountpoint")
    if not source.startswith("/dev/"):
        raise RuntimeError("Filesystem source is not a directly attached block device")
    if expected_device and Path(source).resolve() != Path(expected_device).resolve():
        raise RuntimeError("Mounted block device does not match the expected device")
    if fstype not in {"ext2", "ext3", "ext4", "xfs"}:
        raise RuntimeError(f"Unsupported filesystem type: {fstype or 'unknown'}")

    device_type = _lsblk_value(source, "TYPE")
    parent_device = None
    partition_number = None
    if device_type == "part":
        parent_name = _lsblk_value(source, "PKNAME")
        part_number = _lsblk_value(source, "PARTN")
        if not parent_name or not part_number.isdigit():
            raise RuntimeError("Unable to identify the parent disk and partition number")
        parent_device = f"/dev/{parent_name}"
        partition_number = int(part_number)
    elif device_type != "disk":
        raise RuntimeError(f"Unsupported block-device type: {device_type}")

    return FilesystemPlan(
        mountpoint=str(mountpoint),
        source=source,
        fstype=fstype,
        parent_device=parent_device,
        partition_number=partition_number,
    )


def _filesystem_bytes(mountpoint: Path) -> int:
    output = _run(
        [
            _which("df"),
            "--block-size=1",
            "--output=size",
            str(mountpoint),
        ]
    )
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if len(lines) < 2 or not lines[-1].isdigit():
        raise RuntimeError("Unable to verify filesystem capacity")
    return int(lines[-1])


def expand_filesystem(
    *,
    mountpoint: Path,
    expected_device: str | None,
    expected_minimum_bytes: int,
    dry_run: bool,
) -> dict[str, Any]:
    if os.geteuid() != 0 and not dry_run:
        raise RuntimeError("Filesystem expansion requires the storage controller to run as root")
    plan = filesystem_plan(mountpoint, expected_device)
    before = _filesystem_bytes(mountpoint)
    commands: list[list[str]] = []

    if plan.parent_device and plan.partition_number is not None:
        commands.append(
            [
                _which("growpart"),
                plan.parent_device,
                str(plan.partition_number),
            ]
        )
    if plan.fstype in {"ext2", "ext3", "ext4"}:
        commands.append([_which("resize2fs"), plan.source])
    elif plan.fstype == "xfs":
        commands.append([_which("xfs_growfs"), "-d", str(mountpoint)])

    if not dry_run:
        for command in commands:
            try:
                _run(command, timeout=900)
            except RuntimeError as exc:
                # growpart and filesystem tools are idempotent but may report a
                # no-change condition as nonzero on some distributions. Verify
                # capacity before deciding that the workflow failed.
                if _filesystem_bytes(mountpoint) < expected_minimum_bytes:
                    raise
    after = before if dry_run else _filesystem_bytes(mountpoint)
    if not dry_run and after < expected_minimum_bytes:
        raise RuntimeError(
            f"Filesystem verification failed: {after} bytes is below {expected_minimum_bytes}"
        )
    return {
        "plan": plan.model_dump(),
        "commands": [[Path(item[0]).name, *item[1:]] for item in commands],
        "before_bytes": before,
        "after_bytes": after,
        "verified": dry_run or after >= expected_minimum_bytes,
    }


def _gcp_parts(resource: dict[str, Any]) -> dict[str, str]:
    link = str(resource.get("disk_link") or "").strip().rstrip("/")
    project_override = str(resource.get("project_id") or "").strip()
    match = _GCP_DISK.fullmatch(link)
    if not match:
        raise HTTPException(status_code=422, detail="GCP disk_link is invalid")
    parts = match.groupdict()
    if project_override and project_override != parts["project"]:
        raise HTTPException(status_code=422, detail="GCP project_id does not match disk_link")
    return parts


def _wait_google(operation: Any, label: str, timeout: int = 1800) -> Any:
    result = operation.result(timeout=timeout)
    if getattr(operation, "error_code", None):
        raise RuntimeError(
            f"{label} failed: {operation.error_code}: {getattr(operation, 'error_message', '')}"
        )
    return result


def resize_gcp(request: ResizeRequest) -> dict[str, Any]:
    try:
        from google.cloud import compute_v1
    except ImportError as exc:
        raise RuntimeError("google-cloud-compute is not installed") from exc

    parts = _gcp_parts(request.resource)
    project = parts["project"]
    location = parts["location"]
    disk_name = parts["disk"]
    regional = parts["scope"] == "regions"
    target_gb = int(request.target_size_gib)

    if regional:
        disk_client = compute_v1.RegionDisksClient()
        disk = disk_client.get(project=project, region=location, disk=disk_name)
    else:
        disk_client = compute_v1.DisksClient()
        disk = disk_client.get(project=project, zone=location, disk=disk_name)
    current_gb = int(disk.size_gb)
    if target_gb < current_gb:
        raise RuntimeError("Cloud disks cannot be shrunk")
    if target_gb == current_gb and not request.dry_run:
        return {
            "provider": "gcp",
            "current_size_gib": current_gb,
            "target_size_gib": target_gb,
            "snapshot_id": None,
            "cloud_resize": "already_at_target",
        }

    snapshot_name = None
    if request.snapshot_required:
        snapshot_name = f"amosclaud-{request.request_id[-24:]}-{int(time.time())}".lower()
        snapshot = compute_v1.Snapshot()
        snapshot.name = snapshot_name
        snapshot.source_disk = disk.self_link
        if not request.dry_run:
            snapshot_client = compute_v1.SnapshotsClient()
            operation = snapshot_client.insert(project=project, snapshot_resource=snapshot)
            _wait_google(operation, "GCP snapshot creation")

    if not request.dry_run and target_gb > current_gb:
        if regional:
            resize_request = compute_v1.ResizeRegionDiskRequest()
            resize_request.project = project
            resize_request.region = location
            resize_request.disk = disk_name
            resize_request.region_disks_resize_request_resource = (
                compute_v1.RegionDisksResizeRequest(size_gb=target_gb)
            )
        else:
            resize_request = compute_v1.ResizeDiskRequest()
            resize_request.project = project
            resize_request.zone = location
            resize_request.disk = disk_name
            resize_request.disks_resize_request_resource = (
                compute_v1.DisksResizeRequest(size_gb=target_gb)
            )
        operation = disk_client.resize(resize_request)
        _wait_google(operation, "GCP disk resize")

    return {
        "provider": "gcp",
        "current_size_gib": current_gb,
        "target_size_gib": target_gb,
        "snapshot_id": snapshot_name,
        "cloud_resize": "planned" if request.dry_run else "completed",
    }


def resize_aws(request: ResizeRequest) -> dict[str, Any]:
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is not installed") from exc

    region = str(request.resource.get("region") or "").strip()
    volume_id = str(request.resource.get("volume_id") or "").strip()
    if not region or not re.fullmatch(r"[a-z]{2}(?:-gov)?-[a-z]+-\d", region):
        raise HTTPException(status_code=422, detail="AWS region is invalid")
    if not _AWS_VOLUME.fullmatch(volume_id):
        raise HTTPException(status_code=422, detail="AWS volume_id is invalid")

    ec2 = boto3.client("ec2", region_name=region)
    volumes = ec2.describe_volumes(VolumeIds=[volume_id]).get("Volumes") or []
    if len(volumes) != 1:
        raise RuntimeError("AWS volume was not found")
    current_gib = int(volumes[0]["Size"])
    target_gib = int(request.target_size_gib)
    if target_gib < current_gib:
        raise RuntimeError("Cloud disks cannot be shrunk")

    snapshot_id = None
    if request.snapshot_required:
        if request.dry_run:
            snapshot_id = "dry-run-snapshot"
        else:
            snapshot = ec2.create_snapshot(
                VolumeId=volume_id,
                Description=f"Amosclaud pre-resize snapshot for {request.request_id}",
                TagSpecifications=[
                    {
                        "ResourceType": "snapshot",
                        "Tags": [
                            {"Key": "amosclaud:request", "Value": request.request_id},
                            {"Key": "amosclaud:purpose", "Value": "pre-resize-rollback"},
                        ],
                    }
                ],
            )
            snapshot_id = str(snapshot["SnapshotId"])
            ec2.get_waiter("snapshot_completed").wait(
                SnapshotIds=[snapshot_id],
                WaiterConfig={"Delay": 15, "MaxAttempts": 240},
            )

    state = "already_at_target"
    if target_gib > current_gib:
        if request.dry_run:
            state = "planned"
        else:
            ec2.modify_volume(VolumeId=volume_id, Size=target_gib)
            deadline = time.monotonic() + 7200
            while time.monotonic() < deadline:
                items = ec2.describe_volumes_modifications(VolumeIds=[volume_id]).get(
                    "VolumesModifications",
                    [],
                )
                if items:
                    state = str(items[0].get("ModificationState") or "unknown")
                    if state in {"optimizing", "completed"}:
                        break
                    if state == "failed":
                        raise RuntimeError(
                            str(items[0].get("StatusMessage") or "AWS volume resize failed")
                        )
                time.sleep(10)
            else:
                raise RuntimeError("Timed out waiting for AWS volume resize")

    return {
        "provider": "aws",
        "current_size_gib": current_gib,
        "target_size_gib": target_gib,
        "snapshot_id": snapshot_id,
        "cloud_resize": state,
    }


@app.get("/live")
def live() -> dict[str, Any]:
    return {"status": "ok", "service": "amosclaud-storage-controller"}


@app.get("/ready", dependencies=[Depends(_authorize)])
def ready() -> dict[str, Any]:
    tools = ["findmnt", "lsblk", "df", "growpart", "resize2fs", "xfs_growfs"]
    missing = [name for name in tools if not shutil.which(name, path="/usr/sbin:/usr/bin:/sbin:/bin")]
    return {
        "status": "ready" if _enabled() and not missing else "blocked",
        "detail": (
            "Storage controller is enabled and filesystem tools are available."
            if _enabled() and not missing
            else "Storage controller requires explicit enablement and all filesystem tools."
        ),
        "enabled": _enabled(),
        "providers": ["gcp", "aws"],
        "missing_tools": missing,
        "allowed_mounts": [str(path) for path in _allowed_mount_roots()],
    }


@app.post("/v1/resize", dependencies=[Depends(_authorize)])
def resize(request: ResizeRequest) -> dict[str, Any]:
    if not _enabled():
        raise HTTPException(status_code=503, detail="Storage controller is disabled")
    if not _REQUEST_ID.fullmatch(request.request_id):
        raise HTTPException(status_code=422, detail="request_id is invalid")
    if not request.snapshot_required and not request.dry_run:
        raise HTTPException(status_code=422, detail="A pre-resize snapshot is required")

    mountpoint = _safe_mountpoint(request.mountpoint)
    if request.provider == "gcp":
        cloud_result = resize_gcp(request)
    else:
        cloud_result = resize_aws(request)

    filesystem_result = None
    if request.expand_filesystem:
        filesystem_result = expand_filesystem(
            mountpoint=mountpoint,
            expected_device=request.expected_device,
            expected_minimum_bytes=int(request.target_size_gib) * 1024**3,
            dry_run=request.dry_run,
        )

    return {
        "operation_id": f"storage_{uuid.uuid4().hex}",
        "request_id": request.request_id,
        "status": "planned" if request.dry_run else "completed",
        "cloud": cloud_result,
        "filesystem": filesystem_result,
        "safety": {
            "snapshot_required": request.snapshot_required,
            "mount_allowlist_enforced": True,
            "arbitrary_commands_allowed": False,
            "supported_filesystems": ["ext2", "ext3", "ext4", "xfs"],
            "user_workspace_execution": False,
        },
    }
