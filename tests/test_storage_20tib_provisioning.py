from pathlib import Path

import pytest

from amoscloud_ai import storage_provisioning
from amoscloud_ai.api.routes import auth
from amoscloud_ai.api.routes.storage_capacity import (
    ProvisionJobCreate,
    _provision_confirmation,
    _safe_mountpoint,
)
from amoscloud_ai.main import create_app
from services.storage_controller.volume_provisioner import (
    VolumeProvisionError,
    _validate_request,
    expected_confirmation,
)


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _admin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "auth.db")
    with auth._connect() as db:
        cursor = db.execute(
            """INSERT INTO users(name,email,password_hash,provider,is_admin,created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                "Storage Owner",
                "storage@example.com",
                "hash",
                "password",
                1,
                "2026-07-27T00:00:00+00:00",
            ),
        )
        db.commit()
        return int(cursor.lastrowid)


def test_storage_provisioning_routes_are_registered() -> None:
    paths = {getattr(route, "path", "") for route in create_app().routes}
    assert {
        "/api/v1/admin/storage-capacity/controller",
        "/api/v1/admin/storage-capacity/provision-jobs",
        "/api/v1/admin/storage-capacity/provision-jobs/{job_id}",
    }.issubset(paths)


def test_twenty_tib_profile_and_exact_confirmation_contract() -> None:
    body = ProvisionJobCreate(
        provider="gcp",
        gcp_project_id="amosclaud-prod",
        gcp_zone="us-central1-a",
        gcp_instance_name="workspace-host-1",
        gcp_disk_name="amosclaud-20tb",
        gcp_device_name="amosclaud-20tb",
        size_gib=20480,
        confirmation="PROVISION GCP amosclaud-20tb 20480GiB AND FORMAT EXT4",
    )
    assert body.size_gib == 20480
    assert body.filesystem == "ext4"
    assert body.benchmark_size_gib == 10
    assert body.directory_mode == "2770"
    assert (
        _provision_confirmation("gcp", "amosclaud-20tb", 20480, "ext4")
        == body.confirmation
    )


def test_controller_request_requires_destructive_confirmation() -> None:
    payload = {
        "request_id": "provision_12345678",
        "provider": "gcp",
        "size_gib": 20480,
        "resource": {"disk_name": "amosclaud-20tb"},
        "filesystem": "ext4",
        "filesystem_label": "amosclaud-data",
        "benchmark_size_gib": 10,
        "directory_mode": "2770",
        "confirmation": "wrong",
    }
    with pytest.raises(VolumeProvisionError, match="confirmation"):
        _validate_request(payload)
    payload["confirmation"] = expected_confirmation(payload)
    _validate_request(payload)


def test_managed_mountpoint_rejects_paths_outside_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "AMOSCLOUD_STORAGE_ALLOWED_MOUNT_ROOTS",
        "/mnt/amosclaud-volumes",
    )
    assert _safe_mountpoint("/mnt/amosclaud-volumes/amosclaud-20tb").endswith(
        "/mnt/amosclaud-volumes/amosclaud-20tb"
    )
    with pytest.raises(Exception, match="managed roots"):
        _safe_mountpoint("/etc/amosclaud-volume")


def test_provision_job_is_durable_and_does_not_return_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = _admin(tmp_path, monkeypatch)
    confirmation = "PROVISION AWS amosclaud-20tb 20480GiB AND FORMAT EXT4"
    job = storage_provisioning.create_job(
        requested_by=user_id,
        provider="aws",
        resource={
            "region": "us-east-1",
            "availability_zone": "us-east-1a",
            "instance_id": "i-0123456789abcdef0",
            "volume_name": "amosclaud-20tb",
            "volume_type": "gp3",
            "device_name": "/dev/sdf",
            "iops": 10000,
            "throughput_mibps": 1000,
        },
        size_gib=20480,
        mountpoint="/mnt/amosclaud-volumes/amosclaud-20tb",
        filesystem="ext4",
        filesystem_label="amosclaud-data",
        owner_uid=1000,
        owner_gid=1000,
        directory_mode="2770",
        persist_mount=False,
        benchmark_size_gib=10,
        confirmation=confirmation,
        dry_run=True,
    )
    assert job["status"] == "queued"
    assert job["size_gib"] == 20480
    assert "confirmation" not in job
    persisted = storage_provisioning.get_job(job["id"])
    assert persisted["resource"]["volume_name"] == "amosclaud-20tb"
    assert persisted["events"][0]["event_type"] == "job.queued"


def test_formatting_and_validation_are_fail_closed_by_source_contract() -> None:
    provisioner = _source("services/storage_controller/volume_provisioner.py")
    controller_api = _source("services/storage_controller/volume_api.py")
    validator = _source("scripts/validate_workspace_volume.sh")
    dockerfile = _source("services/storage_controller/Dockerfile")
    worker = _source("amoscloud_ai/worker.py")

    assert "Refusing to format the operating-system disk" in provisioner
    assert "existing disk signature" in provisioner
    assert '"--clear"' in provisioner
    assert '"64bit,metadata_csum"' in provisioner
    assert '"--verify=sha256"' in provisioner
    assert "world_writable_mount" in controller_api
    assert "chmod a+w" not in provisioner
    assert "chmod a+w" not in validator
    assert "TEST_GIB <= 100" in validator
    assert "trap cleanup EXIT INT TERM" in validator
    assert "fio" in dockerfile
    assert "gdisk" in dockerfile
    assert "nvme-cli" in dockerfile
    assert "def run_storage_provision" in worker
    assert "recover_storage_provisions" in worker


def test_public_api_never_runs_mkfs_or_cloud_attach_commands() -> None:
    public_orchestrator = _source("amoscloud_ai/storage_provisioning.py")
    api = _source("amoscloud_ai/api/routes/storage_capacity.py")
    privileged = _source("services/storage_controller/volume_provisioner.py")

    assert "mkfs.ext4" not in public_orchestrator
    assert "attach_volume" not in public_orchestrator
    assert "attach_disk" not in public_orchestrator
    assert "subprocess.run" not in api
    assert "mkfs.ext4" in privileged
    assert "attach_volume" in privileged
    assert "attach_disk" in privileged
