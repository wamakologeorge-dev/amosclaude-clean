from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from amoscloud_ai.control_plane import (
    ControlPlaneIdentity,
    ExecutionTarget,
    JobExpiredError,
    PermissionDeniedError,
    SignatureVerificationError,
    verify_authorized_job,
)

NOW = datetime(2026, 8, 6, 18, 0, tzinfo=timezone.utc)


def _identity() -> ControlPlaneIdentity:
    return ControlPlaneIdentity.from_seed(bytes(range(32)))


def _authorized_job(identity: ControlPlaneIdentity) -> dict:
    return identity.authorize_job(
        job_id="job_123",
        account_id=42,
        workspace_id="workspace_primary",
        target=ExecutionTarget.LOCAL_COMPUTER,
        runner_id="runner_laptop",
        repository="wamakologeorge-dev/amosclaude-clean",
        objective="Run tests and prepare a verified patch.",
        permissions=[
            "repository:read",
            "workspace:write",
            "tests:run",
            "patch:create",
        ],
        request={"branch": "main", "mode": "fix"},
        issued_at=NOW,
        ttl_seconds=300,
        nonce="fixed-test-nonce",
    )


def test_control_plane_job_round_trip_is_target_and_account_bound() -> None:
    identity = _identity()
    envelope = _authorized_job(identity)

    authorization = verify_authorized_job(
        envelope,
        public_key=identity.public_key,
        expected_key_id=identity.key_id,
        expected_target=ExecutionTarget.LOCAL_COMPUTER,
        expected_runner_id="runner_laptop",
        expected_account_id=42,
        now=NOW + timedelta(seconds=10),
    )

    assert authorization["job_id"] == "job_123"
    assert authorization["target"] == "local_computer"
    assert authorization["account_id"] == "42"
    assert authorization["request"] == {"branch": "main", "mode": "fix"}
    assert len(authorization["idempotency_key"]) == 64


def test_tampered_job_is_rejected_before_execution() -> None:
    identity = _identity()
    envelope = deepcopy(_authorized_job(identity))
    envelope["authorization"]["objective"] = "Delete the repository."

    with pytest.raises(SignatureVerificationError, match="signature is invalid"):
        verify_authorized_job(
            envelope,
            public_key=identity.public_key,
            now=NOW + timedelta(seconds=10),
        )


def test_expired_job_cannot_be_replayed() -> None:
    identity = _identity()
    envelope = identity.authorize_job(
        job_id="job_expiring",
        account_id=42,
        workspace_id="workspace_primary",
        target=ExecutionTarget.PRIVATE_SERVER,
        objective="Inspect service health.",
        permissions=["monitoring:read"],
        issued_at=NOW,
        ttl_seconds=30,
    )

    with pytest.raises(JobExpiredError, match="expired"):
        verify_authorized_job(
            envelope,
            public_key=identity.public_key,
            now=NOW + timedelta(seconds=31),
        )


def test_sensitive_permissions_require_explicit_developer_approval() -> None:
    identity = _identity()

    with pytest.raises(PermissionDeniedError, match="explicit developer approval"):
        identity.authorize_job(
            job_id="job_deploy",
            account_id=42,
            workspace_id="workspace_primary",
            target=ExecutionTarget.PRIVATE_SERVER,
            objective="Deploy the approved release.",
            permissions=["deployment:execute"],
            issued_at=NOW,
        )

    envelope = identity.authorize_job(
        job_id="job_deploy",
        account_id=42,
        workspace_id="workspace_primary",
        target=ExecutionTarget.PRIVATE_SERVER,
        objective="Deploy the approved release.",
        permissions=["deployment:execute"],
        sensitive_approved=True,
        issued_at=NOW,
    )

    verified = verify_authorized_job(
        envelope,
        public_key=identity.public_key,
        expected_target=ExecutionTarget.PRIVATE_SERVER,
        now=NOW + timedelta(seconds=1),
    )
    assert verified["sensitive_approved"] is True


def test_runner_rejects_job_for_another_execution_target() -> None:
    identity = _identity()
    envelope = _authorized_job(identity)

    with pytest.raises(SignatureVerificationError, match="different execution target"):
        verify_authorized_job(
            envelope,
            public_key=identity.public_key,
            expected_target=ExecutionTarget.GITHUB_REPOSITORY,
            now=NOW + timedelta(seconds=1),
        )


def test_public_identity_exposes_only_verification_material() -> None:
    identity = _identity()

    public_identity = identity.public_identity()

    assert public_identity["algorithm"] == "Ed25519"
    assert public_identity["key_id"] == identity.key_id
    assert public_identity["public_key"] == identity.public_key
    assert "private_key" not in public_identity
    assert "signing_key" not in public_identity
