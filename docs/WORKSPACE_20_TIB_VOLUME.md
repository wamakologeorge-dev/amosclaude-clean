# Amosclaud 20 TiB Workspace Volume

Amosclaud provisions large workspace storage through a private infrastructure controller. The public FastAPI service records an administrator-approved job; it does not hold cloud credentials, execute `mkfs`, attach block devices, or run privileged commands inside a developer workspace.

## Architecture

```text
Administrator API
    |
    | durable provision job
    v
Celery worker
    |
    | authenticated private request
    v
Storage controller on the workspace host
    |
    +--> create encrypted GCP Persistent Disk or AWS EBS volume
    +--> attach it to the selected host
    +--> prove the local block device belongs to that cloud volume
    +--> block root disks, mounts, partitions, filesystems, and signatures
    +--> create GPT partition table
    +--> format ext4 or XFS
    +--> mount with owner/group mode 2770
    +--> optionally persist by filesystem UUID
    +--> verify visible capacity
    +--> run bounded fio SHA-256 write/read verification
```

The default large profile is **20,480 GiB (20 TiB)**. The configured maximum is controlled by `AMOSCLAUD_STORAGE_MAX_SIZE_GIB` and cannot exceed 65,536 GiB.

## Why the original shell example was hardened

The platform does not use a fixed `/dev/sdb` name. Cloud block-device names can change, especially on NVMe-based hosts. GCP uses the stable `/dev/disk/by-id/google-<device-name>` link. AWS volumes are resolved by matching the EBS volume ID to the NVMe serial reported by `lsblk`.

The platform also does not run `chmod a+w`. The mounted workspace directory defaults to UID 1000, GID 1000, and mode `2770`, so only the assigned owner and group can write.

A 20 TiB data volume uses GPT. MBR cannot address a volume above 2 TiB. The ext4 formatter explicitly enables the 64-bit filesystem feature.

The performance test uses `fio` with direct I/O and SHA-256 verification instead of a zero-filled `dd` file. It is capped at 100 GiB and defaults to 10 GiB.

## Private controller deployment

```bash
export AMOSCLAUD_STORAGE_CONTROLLER_TOKEN="$(openssl rand -hex 32)"
docker compose -f docker-compose.storage-controller.yml up -d --build
```

The controller must run only on the storage host or a dedicated infrastructure node. It requires block-device and mount privileges. Its HTTP listener is bound to `127.0.0.1:8090`.

Recommended cloud authorization:

- GCP: attach a narrowly scoped service account to the storage host or use Workload Identity.
- AWS: attach a narrowly scoped instance profile to the storage host.
- Do not place cloud credentials in a developer container or repository.

## Required environment variables

Public control plane and worker:

```text
AMOSCLAUD_STORAGE_CONTROLLER_URL=http://PRIVATE_CONTROLLER_IP:8090
AMOSCLAUD_STORAGE_CONTROLLER_TOKEN=<same random controller token>
AMOSCLAUD_STORAGE_MAX_SIZE_GIB=20480
AMOSCLAUD_STORAGE_PROVISION_TIMEOUT_SECONDS=21600
AMOSCLOUD_STORAGE_ALLOWED_MOUNT_ROOTS=/mnt/amosclaud-volumes
```

Private controller:

```text
AMOSCLAUD_STORAGE_CONTROLLER_ENABLED=true
AMOSCLAUD_STORAGE_CONTROLLER_TOKEN=<same random controller token>
AMOSCLAUD_STORAGE_ALLOWED_MOUNTS=/mnt/amosclaud-volumes
AMOSCLAUD_STORAGE_FSTAB_PATH=/host/etc/fstab
```

`AMOSCLAUD_STORAGE_FSTAB_PATH` is required only when `persist_mount=true`.

## GCP 20 TiB dry run

```bash
curl -X POST \
  https://www.amosclaud.com/api/v1/admin/storage-capacity/provision-jobs \
  -H "Content-Type: application/json" \
  -b "amos_session=$AMOS_SESSION" \
  -d '{
    "provider": "gcp",
    "size_gib": 20480,
    "mountpoint": "/mnt/amosclaud-volumes/amosclaud-20tb",
    "filesystem": "ext4",
    "filesystem_label": "amosclaud-data",
    "owner_uid": 1000,
    "owner_gid": 1000,
    "directory_mode": "2770",
    "persist_mount": false,
    "benchmark_size_gib": 10,
    "dry_run": true,
    "gcp_project_id": "PROJECT_ID",
    "gcp_zone": "us-central1-a",
    "gcp_instance_name": "workspace-host-1",
    "gcp_disk_name": "amosclaud-20tb",
    "gcp_device_name": "amosclaud-20tb",
    "gcp_disk_type": "pd-balanced",
    "confirmation": "PROVISION GCP amosclaud-20tb 20480GiB AND FORMAT EXT4"
  }'
```

After reviewing the planned result, repeat with `"dry_run": false`.

## AWS 20 TiB dry run

```bash
curl -X POST \
  https://www.amosclaud.com/api/v1/admin/storage-capacity/provision-jobs \
  -H "Content-Type: application/json" \
  -b "amos_session=$AMOS_SESSION" \
  -d '{
    "provider": "aws",
    "size_gib": 20480,
    "mountpoint": "/mnt/amosclaud-volumes/amosclaud-20tb",
    "filesystem": "ext4",
    "filesystem_label": "amosclaud-data",
    "owner_uid": 1000,
    "owner_gid": 1000,
    "directory_mode": "2770",
    "persist_mount": false,
    "benchmark_size_gib": 10,
    "dry_run": true,
    "aws_region": "us-east-1",
    "aws_availability_zone": "us-east-1a",
    "aws_instance_id": "i-0123456789abcdef0",
    "aws_volume_name": "amosclaud-20tb",
    "aws_volume_type": "gp3",
    "aws_device_name": "/dev/sdf",
    "aws_iops": 10000,
    "aws_throughput_mibps": 1000,
    "confirmation": "PROVISION AWS amosclaud-20tb 20480GiB AND FORMAT EXT4"
  }'
```

The AWS attachment device is an API mapping name. On Nitro instances the operating system can expose a different `/dev/nvme...` path; the controller resolves the actual device by EBS volume ID.

## Independent validation script

After the controller reports completion, the host operator can run:

```bash
sudo bash scripts/validate_workspace_volume.sh \
  /mnt/amosclaud-volumes/amosclaud-20tb \
  20480 \
  10
```

Arguments:

1. mounted filesystem path;
2. expected capacity in GiB;
3. bounded fio verification size in GiB.

The script refuses an unmounted path, verifies the backing device and filesystem, requires at least 97% of the requested raw capacity to be visible after filesystem metadata, executes direct-I/O SHA-256 verification, syncs caches, and removes the temporary validation file.

## Safety and failure behavior

- Existing disks are never automatically reformatted.
- A disk with a partition, mount, filesystem, or signature is rejected.
- The root filesystem and its parent disk are rejected.
- Cloud resources are encrypted when the provider supports an encryption option.
- Exact typed confirmation is required.
- No automatic cloud-volume deletion occurs after a partial failure. A newly created resource is preserved for investigation rather than risking deletion of the wrong disk.
- The job is not marked complete unless cloud attachment, formatting, mounting, capacity checks, and fio validation all return verified evidence.
- A failed benchmark leaves a failed job and removes its temporary test file.
- Production deployment should alert an operator when provisioning stops after cloud creation but before mount verification.
