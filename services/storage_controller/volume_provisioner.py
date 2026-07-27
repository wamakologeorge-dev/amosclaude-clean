"""Guarded cloud-volume provisioning for the private storage controller.

This module is intentionally unavailable to developer workspaces. It creates and
attaches a new cloud volume, proves the attached block device belongs to that
cloud resource, refuses any device with existing signatures or mounts, creates a
GPT partition, formats ext4/XFS, mounts with restricted permissions, and runs a
bounded fio verification workload.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

_GCP_NAME = re.compile(r"^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$")
_AWS_INSTANCE = re.compile(r"^i-[0-9a-fA-F]{8,32}$")
_AWS_VOLUME = re.compile(r"^vol-[0-9a-fA-F]{8,32}$")
_AWS_REGION = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z]+-\d$")
_LABEL = re.compile(r"^[A-Za-z0-9_.-]{1,16}$")
_SUPPORTED_FILESYSTEMS = {"ext4", "xfs"}
_AWS_MAX_GIB = {
    "gp2": 16384,
    "gp3": 65536,
    "io1": 16384,
    "io2": 65536,
    "st1": 16384,
    "sc1": 16384,
}
_GCP_DISK_TYPES = {"pd-balanced", "pd-ssd", "pd-standard"}


class VolumeProvisionError(RuntimeError):
    """Raised when cloud provisioning or host verification stops safely."""


def _which(name: str) -> str:
    path = shutil.which(name, path="/usr/sbin:/usr/bin:/sbin:/bin")
    if not path:
        raise VolumeProvisionError(f"Required storage tool is unavailable: {name}")
    return path


def _run(command: list[str], *, timeout: int = 120) -> str:
    if not command or not Path(command[0]).is_absolute():
        raise VolumeProvisionError("Storage commands must use absolute executables")
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
        raise VolumeProvisionError(
            f"{Path(command[0]).name} failed with exit code "
            f"{completed.returncode}: {output[:2_000]}"
        )
    return output


def _wait_google(operation: Any, label: str, timeout: int = 3600) -> None:
    operation.result(timeout=timeout)
    if getattr(operation, "error_code", None):
        raise VolumeProvisionError(
            f"{label} failed: {operation.error_code}: "
            f"{getattr(operation, 'error_message', '')}"
        )


def _cloud_name(request: dict[str, Any]) -> str:
    resource = dict(request.get("resource") or {})
    if request["provider"] == "gcp":
        return str(resource.get("disk_name") or "").strip()
    return str(resource.get("volume_name") or "").strip()


def expected_confirmation(request: dict[str, Any]) -> str:
    return (
        f"PROVISION {str(request['provider']).upper()} {_cloud_name(request)} "
        f"{int(request['size_gib'])}GiB AND FORMAT "
        f"{str(request['filesystem']).upper()}"
    )


def _validate_request(request: dict[str, Any]) -> None:
    size_gib = int(request["size_gib"])
    if not 10 <= size_gib <= 65536:
        raise VolumeProvisionError("Volume size must be between 10 and 65536 GiB")
    filesystem = str(request["filesystem"]).lower()
    if filesystem not in _SUPPORTED_FILESYSTEMS:
        raise VolumeProvisionError("Only ext4 and XFS are supported")
    label = str(request.get("filesystem_label") or "").strip()
    if not _LABEL.fullmatch(label):
        raise VolumeProvisionError(
            "Filesystem labels must contain 1-16 letters, numbers, dots, dashes, or underscores"
        )
    if request.get("confirmation") != expected_confirmation(request):
        raise VolumeProvisionError("Destructive provisioning confirmation does not match")
    benchmark = int(request.get("benchmark_size_gib") or 0)
    if not 0 <= benchmark <= 100:
        raise VolumeProvisionError("Benchmark size must be between 0 and 100 GiB")


def _provision_gcp(request: dict[str, Any]) -> dict[str, Any]:
    try:
        from google.cloud import compute_v1
    except ImportError as exc:
        raise VolumeProvisionError("google-cloud-compute is not installed") from exc

    resource = dict(request["resource"])
    project = str(resource.get("project_id") or "").strip()
    zone = str(resource.get("zone") or "").strip()
    instance = str(resource.get("instance_name") or "").strip()
    disk_name = str(resource.get("disk_name") or "").strip()
    device_name = str(resource.get("device_name") or disk_name).strip()
    disk_type = str(resource.get("disk_type") or "pd-balanced").strip()
    if not project or not zone or not instance:
        raise VolumeProvisionError(
            "GCP provisioning requires project_id, zone, and instance_name"
        )
    if not _GCP_NAME.fullmatch(disk_name) or not _GCP_NAME.fullmatch(device_name):
        raise VolumeProvisionError("GCP disk and device names are invalid")
    if disk_type not in _GCP_DISK_TYPES:
        raise VolumeProvisionError("Unsupported GCP Persistent Disk type")

    planned = {
        "provider": "gcp",
        "project_id": project,
        "zone": zone,
        "instance_name": instance,
        "disk_name": disk_name,
        "device_name": device_name,
        "disk_type": disk_type,
        "size_gib": int(request["size_gib"]),
        "stable_device": f"/dev/disk/by-id/google-{device_name}",
    }
    if request.get("dry_run"):
        return {**planned, "state": "planned", "created": False, "attached": False}

    disks = compute_v1.DisksClient()
    instances = compute_v1.InstancesClient()
    try:
        existing = disks.get(project=project, zone=zone, disk=disk_name)
    except Exception:
        existing = None
    if existing is not None:
        raise VolumeProvisionError(
            "GCP disk already exists; automatic formatting is allowed only for a newly created disk"
        )

    disk = compute_v1.Disk(
        name=disk_name,
        size_gb=int(request["size_gib"]),
        type_=f"zones/{zone}/diskTypes/{disk_type}",
        labels={
            "managed-by": "amosclaud",
            "request-id": str(request["request_id"])[-63:].lower(),
        },
        physical_block_size_bytes=4096,
    )
    operation = disks.insert(project=project, zone=zone, disk_resource=disk)
    _wait_google(operation, "GCP disk creation")
    created = disks.get(project=project, zone=zone, disk=disk_name)

    attached = compute_v1.AttachedDisk(
        source=created.self_link,
        device_name=device_name,
        auto_delete=False,
        boot=False,
    )
    operation = instances.attach_disk(
        project=project,
        zone=zone,
        instance=instance,
        attached_disk_resource=attached,
    )
    _wait_google(operation, "GCP disk attachment")
    return {
        **planned,
        "state": "attached",
        "created": True,
        "attached": True,
        "cloud_resource_id": created.self_link,
    }


def _provision_aws(request: dict[str, Any]) -> dict[str, Any]:
    try:
        import boto3
    except ImportError as exc:
        raise VolumeProvisionError("boto3 is not installed") from exc

    resource = dict(request["resource"])
    region = str(resource.get("region") or "").strip()
    availability_zone = str(resource.get("availability_zone") or "").strip()
    instance_id = str(resource.get("instance_id") or "").strip()
    volume_name = str(resource.get("volume_name") or "").strip()
    volume_type = str(resource.get("volume_type") or "gp3").strip()
    device_name = str(resource.get("device_name") or "/dev/sdf").strip()
    size_gib = int(request["size_gib"])
    if not _AWS_REGION.fullmatch(region):
        raise VolumeProvisionError("AWS region is invalid")
    if not availability_zone.startswith(region) or len(availability_zone) > 32:
        raise VolumeProvisionError("AWS availability zone is invalid")
    if not _AWS_INSTANCE.fullmatch(instance_id):
        raise VolumeProvisionError("AWS instance ID is invalid")
    if not re.fullmatch(r"[A-Za-z0-9_.:/=+@-]{1,128}", volume_name):
        raise VolumeProvisionError("AWS volume name is invalid")
    if volume_type not in _AWS_MAX_GIB or size_gib > _AWS_MAX_GIB[volume_type]:
        raise VolumeProvisionError(
            f"AWS {volume_type} does not support a {size_gib} GiB volume"
        )
    if not re.fullmatch(r"/dev/sd[f-p]", device_name):
        raise VolumeProvisionError("AWS attachment device must be between /dev/sdf and /dev/sdp")

    planned = {
        "provider": "aws",
        "region": region,
        "availability_zone": availability_zone,
        "instance_id": instance_id,
        "volume_name": volume_name,
        "volume_type": volume_type,
        "attachment_device": device_name,
        "size_gib": size_gib,
    }
    if request.get("dry_run"):
        return {**planned, "state": "planned", "created": False, "attached": False}

    ec2 = boto3.client("ec2", region_name=region)
    create_args: dict[str, Any] = {
        "AvailabilityZone": availability_zone,
        "Size": size_gib,
        "VolumeType": volume_type,
        "Encrypted": True,
        "ClientToken": str(request["request_id"])[:64],
        "TagSpecifications": [
            {
                "ResourceType": "volume",
                "Tags": [
                    {"Key": "Name", "Value": volume_name},
                    {"Key": "amosclaud:managed", "Value": "true"},
                    {"Key": "amosclaud:request", "Value": str(request["request_id"])},
                ],
            }
        ],
    }
    iops = resource.get("iops")
    throughput = resource.get("throughput_mibps")
    if volume_type in {"io1", "io2"}:
        create_args["Iops"] = int(iops or 10000)
    elif volume_type == "gp3":
        if iops is not None:
            create_args["Iops"] = int(iops)
        if throughput is not None:
            create_args["Throughput"] = int(throughput)

    response = ec2.create_volume(**create_args)
    volume_id = str(response["VolumeId"])
    if not _AWS_VOLUME.fullmatch(volume_id):
        raise VolumeProvisionError("AWS returned an invalid volume ID")
    ec2.get_waiter("volume_available").wait(
        VolumeIds=[volume_id],
        WaiterConfig={"Delay": 10, "MaxAttempts": 180},
    )
    ec2.attach_volume(
        Device=device_name,
        InstanceId=instance_id,
        VolumeId=volume_id,
    )
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        volumes = ec2.describe_volumes(VolumeIds=[volume_id]).get("Volumes") or []
        attachments = volumes[0].get("Attachments") if volumes else []
        if attachments and attachments[0].get("State") == "attached":
            break
        time.sleep(5)
    else:
        raise VolumeProvisionError("Timed out waiting for AWS volume attachment")
    return {
        **planned,
        "state": "attached",
        "created": True,
        "attached": True,
        "cloud_resource_id": volume_id,
        "volume_id": volume_id,
    }


def _wait_for_path(path: Path, timeout: int = 300) -> Path:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return path.resolve()
        time.sleep(2)
    raise VolumeProvisionError(f"Attached block device did not appear: {path}")


def _resolve_aws_device(volume_id: str, timeout: int = 300) -> Path:
    expected_serial = volume_id.replace("-", "").lower()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = json.loads(
            _run(
                [
                    _which("lsblk"),
                    "--json",
                    "--bytes",
                    "--output",
                    "PATH,TYPE,SERIAL,RO,MOUNTPOINTS",
                ]
            )
        )
        matches = []
        for item in payload.get("blockdevices") or []:
            serial = str(item.get("serial") or "").replace("-", "").lower()
            if serial == expected_serial and item.get("type") == "disk":
                matches.append(Path(str(item["path"])).resolve())
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise VolumeProvisionError("Multiple block devices matched the AWS volume ID")
        time.sleep(2)
    raise VolumeProvisionError("Unable to map the attached AWS volume ID to one NVMe device")


def _device_tree(device: Path) -> dict[str, Any]:
    payload = json.loads(
        _run(
            [
                _which("lsblk"),
                "--json",
                "--bytes",
                "--output",
                "PATH,TYPE,SIZE,RO,FSTYPE,MOUNTPOINTS,SERIAL,PKNAME,PARTN",
                str(device),
            ]
        )
    )
    devices = payload.get("blockdevices") or []
    if len(devices) != 1:
        raise VolumeProvisionError("Expected exactly one attached block device")
    return devices[0]


def _root_parent_devices() -> set[Path]:
    source = _run([_which("findmnt"), "--noheadings", "--output", "SOURCE", "/"]).strip()
    if not source.startswith("/dev/"):
        return set()
    path = Path(source).resolve()
    protected = {path}
    try:
        parent = _run([_which("lsblk"), "--noheadings", "--output", "PKNAME", str(path)]).strip()
    except VolumeProvisionError:
        parent = ""
    if parent:
        protected.add(Path(f"/dev/{parent}").resolve())
    return protected


def _validate_blank_device(device: Path, *, expected_size_gib: int) -> dict[str, Any]:
    resolved = device.resolve()
    if not str(resolved).startswith("/dev/"):
        raise VolumeProvisionError("Resolved device is outside /dev")
    if resolved in _root_parent_devices():
        raise VolumeProvisionError("Refusing to format the operating-system disk")
    tree = _device_tree(resolved)
    if tree.get("type") != "disk" or int(tree.get("ro") or 0) != 0:
        raise VolumeProvisionError("Attached resource is not one writable whole-disk block device")
    if tree.get("children"):
        raise VolumeProvisionError("New cloud volume unexpectedly contains partitions")
    if any(tree.get("mountpoints") or []):
        raise VolumeProvisionError("New cloud volume is already mounted")
    if tree.get("fstype"):
        raise VolumeProvisionError("New cloud volume already contains a filesystem")
    signatures = _run([_which("wipefs"), "--noheadings", "--output", "TYPE", str(resolved)]).strip()
    if signatures:
        raise VolumeProvisionError("New cloud volume contains an existing disk signature")
    size_bytes = int(tree.get("size") or 0)
    expected_bytes = int(expected_size_gib) * 1024**3
    tolerance = 1024**3
    if size_bytes + tolerance < expected_bytes:
        raise VolumeProvisionError(
            f"Attached block device exposes {size_bytes} bytes, below the requested {expected_bytes}"
        )
    return {
        "device": str(resolved),
        "size_bytes": size_bytes,
        "expected_bytes": expected_bytes,
        "serial": tree.get("serial"),
        "blank": True,
    }


def _partition_path(device: Path) -> Path:
    suffix = "p1" if device.name[-1:].isdigit() else "1"
    return Path(f"{device}{suffix}")


def _mount_is_safe(mountpoint: Path) -> None:
    if mountpoint.exists() and mountpoint.is_mount():
        raise VolumeProvisionError("Mountpoint is already mounted")
    if mountpoint.exists() and any(mountpoint.iterdir()):
        raise VolumeProvisionError("Mountpoint must be empty before a new volume is mounted")


def _filesystem_uuid(partition: Path) -> str:
    value = _run([_which("blkid"), "--output", "value", "--match-tag", "UUID", str(partition)]).strip()
    if not value or not re.fullmatch(r"[A-Fa-f0-9-]{8,64}", value):
        raise VolumeProvisionError("Unable to read the new filesystem UUID")
    return value


def _persist_mount(
    *,
    uuid_value: str,
    mountpoint: Path,
    filesystem: str,
    mount_options: str,
) -> str:
    configured = os.getenv("AMOSCLAUD_STORAGE_FSTAB_PATH", "").strip()
    if not configured:
        raise VolumeProvisionError(
            "Persistent mounts require AMOSCLAUD_STORAGE_FSTAB_PATH to reference the host fstab"
        )
    fstab = Path(configured).resolve()
    if fstab.name != "fstab" or not fstab.exists() or not fstab.is_file():
        raise VolumeProvisionError("Configured host fstab path is invalid")
    original = fstab.read_text(encoding="utf-8")
    marker = f"UUID={uuid_value}"
    if marker in original:
        return marker
    line = f"{marker} {mountpoint} {filesystem} {mount_options},nofail 0 2\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(fstab.parent),
        prefix=".amosclaud-fstab-",
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        stream.write(original)
        if original and not original.endswith("\n"):
            stream.write("\n")
        stream.write(line)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, fstab.stat().st_mode & 0o777)
    os.replace(temporary, fstab)
    return marker


def _fio_summary(mountpoint: Path, size_gib: int) -> dict[str, Any] | None:
    if size_gib <= 0:
        return None
    fio_path = mountpoint / ".amosclaud-storage-validation.fio"
    try:
        output = _run(
            [
                _which("fio"),
                "--name=amosclaud-integrity",
                f"--filename={fio_path}",
                f"--size={size_gib}G",
                "--rw=write",
                "--bs=1M",
                "--iodepth=16",
                "--direct=1",
                "--verify=sha256",
                "--do_verify=1",
                "--verify_fatal=1",
                "--fsync_on_close=1",
                "--output-format=json",
            ],
            timeout=max(1800, size_gib * 900),
        )
        payload = json.loads(output)
        jobs = payload.get("jobs") or []
        if len(jobs) != 1 or int(jobs[0].get("error") or 0) != 0:
            raise VolumeProvisionError("fio reported a storage verification error")
        job = jobs[0]
        return {
            "size_gib": size_gib,
            "verified": True,
            "write_bytes": int((job.get("write") or {}).get("io_bytes") or 0),
            "write_bandwidth_bytes_per_second": int(
                (job.get("write") or {}).get("bw_bytes") or 0
            ),
            "read_bytes": int((job.get("read") or {}).get("io_bytes") or 0),
            "read_bandwidth_bytes_per_second": int(
                (job.get("read") or {}).get("bw_bytes") or 0
            ),
        }
    finally:
        try:
            fio_path.unlink(missing_ok=True)
        except OSError:
            pass


def format_mount_and_verify(
    request: dict[str, Any],
    *,
    device: Path,
    mountpoint: Path,
) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise VolumeProvisionError("Formatting requires the private controller to run as root")
    _mount_is_safe(mountpoint)
    blank = _validate_blank_device(device, expected_size_gib=int(request["size_gib"]))
    filesystem = str(request["filesystem"]).lower()
    label = str(request["filesystem_label"])

    _run([_which("sgdisk"), "--clear", str(device)])
    _run(
        [
            _which("sgdisk"),
            "--new=1:0:0",
            "--typecode=1:8300",
            f"--change-name=1:{label}",
            str(device),
        ]
    )
    _run([_which("partprobe"), str(device)])
    _run([_which("udevadm"), "settle", "--timeout=60"])
    partition = _wait_for_path(_partition_path(device), timeout=120)

    if filesystem == "ext4":
        _run(
            [
                _which("mkfs.ext4"),
                "-F",
                "-m",
                "1",
                "-O",
                "64bit,metadata_csum",
                "-E",
                "lazy_itable_init=0,lazy_journal_init=0",
                "-L",
                label,
                str(partition),
            ],
            timeout=7200,
        )
        mount_options = "defaults,noatime"
    else:
        _run(
            [
                _which("mkfs.xfs"),
                "-f",
                "-s",
                "size=4096",
                "-L",
                label,
                str(partition),
            ],
            timeout=7200,
        )
        mount_options = "defaults,noatime,inode64"

    mountpoint.mkdir(parents=True, exist_ok=True)
    os.chown(mountpoint, int(request["owner_uid"]), int(request["owner_gid"]))
    os.chmod(mountpoint, int(str(request["directory_mode"]), 8))
    _run([_which("mount"), "--options", mount_options, str(partition), str(mountpoint)])
    uuid_value = _filesystem_uuid(partition)
    persisted = None
    if request.get("persist_mount"):
        persisted = _persist_mount(
            uuid_value=uuid_value,
            mountpoint=mountpoint,
            filesystem=filesystem,
            mount_options=mount_options,
        )

    capacity_bytes = int(
        _run(
            [
                _which("df"),
                "--block-size=1",
                "--output=size",
                str(mountpoint),
            ]
        ).splitlines()[-1].strip()
    )
    requested_bytes = int(request["size_gib"]) * 1024**3
    # Filesystem metadata and the 1% ext4 reserve mean df capacity is lower than
    # raw block size. Ninety-seven percent is a strict but realistic lower bound.
    minimum_bytes = int(requested_bytes * 0.97)
    if capacity_bytes < minimum_bytes:
        raise VolumeProvisionError(
            f"Mounted filesystem exposes {capacity_bytes} bytes; expected at least {minimum_bytes}"
        )

    benchmark = _fio_summary(mountpoint, int(request.get("benchmark_size_gib") or 0))
    _run([_which("sync")])
    return {
        "blank_device_check": blank,
        "partition": str(partition),
        "filesystem": filesystem,
        "filesystem_uuid": uuid_value,
        "mountpoint": str(mountpoint),
        "mount_options": mount_options,
        "persisted_mount": persisted,
        "capacity_bytes": capacity_bytes,
        "minimum_expected_bytes": minimum_bytes,
        "directory_owner": {
            "uid": int(request["owner_uid"]),
            "gid": int(request["owner_gid"]),
            "mode": str(request["directory_mode"]),
        },
        "benchmark": benchmark,
        "verified": True,
    }


def provision_volume(request: dict[str, Any], *, mountpoint: Path) -> dict[str, Any]:
    _validate_request(request)
    cloud = (
        _provision_gcp(request)
        if request["provider"] == "gcp"
        else _provision_aws(request)
    )
    if request.get("dry_run"):
        return {"cloud": cloud, "host": None, "verified": True, "dry_run": True}

    if request["provider"] == "gcp":
        device = _wait_for_path(Path(str(cloud["stable_device"])), timeout=300)
    else:
        device = _resolve_aws_device(str(cloud["volume_id"]), timeout=300)
    host = format_mount_and_verify(request, device=device, mountpoint=mountpoint)
    return {
        "cloud": cloud,
        "host": host,
        "verified": bool(host["verified"]),
        "dry_run": False,
    }
