from datetime import datetime, timedelta, timezone

import pytest

from amoscloud_ai.control_plane import (
    ControlPlaneError,
    ControlPlaneIdentity,
    ExecutionTarget,
    PermissionDeniedError,
    verify_authorized_job,
)
from amoscloud_ai.control_plane_bridge import (
    execution_target_for_task,
    permissions_for_task,
    sign_task_record,
)

NOW = datetime(2026, 8, 6, 18, 0, tzinfo=timezone.utc)


def _identity() -> ControlPlaneIdentity:
    return ControlPlaneIdentity.from_seed(bytes(reversed(range(32))))


def _task(**overrides):
    task = {
        "id": "task_123",
        "account_id": "42",
        "bucket_id": "bucket_primary",
        "repository": "owner/repository",
        "objective": "Fix the failing tests and prepare a pull request.",
        "mode": "fix",
        "delivery": "pull_request",
        "status": "running",
        "execution_target": "self_hosted",
        "runner_id": "runner_laptop",
        "metadata": {"branch": "main"},
    }
    task.update(overrides)
    return task


def test_local_runner_task_becomes_signed_local_computer_job() -> None:
    identity = _identity()

    envelope = sign_task_record(
        _task(),
        identity=identity,
        account_id=42,
        workspace_id="workspace_primary",
        runner_kind="local_computer",
        issued_at=NOW,
        nonce="fixed-local-runner-nonce",
    )
    authorization = verify_authorized_job(
        envelope,
        public_key=identity.public_key,
        expected_target=ExecutionTarget.LOCAL_COMPUTER,
        expected_runner_id="runner_laptop",
        expected_account_id=42,
        now=NOW + timedelta(seconds=1),
    )

    assert authorization["job_id"] == "task_123"
    assert authorization["request"]["mode"] == "fix"
    assert "tests:run" in authorization["permissions"]
    assert "github:pull_request:create" in authorization["permissions"]


def test_github_task_maps_to_github_app_target() -> None:
    task = _task(
        execution_target="github",
        runner_id=None,
        mode="review",
        delivery="report",
    )

    assert execution_target_for_task(task) is ExecutionTarget.GITHUB_REPOSITORY
    assert permissions_for_task(task) == (
        "logs:write",
        "repository:read",
        "workspace:read",
    )


def test_private_server_deployment_requires_sensitive_approval() -> None:
    identity = _identity()
    task = _task(
        execution_target="self_hosted",
        runner_id="runner_server",
        mode="deploy",
        delivery="report",
    )

    with pytest.raises(PermissionDeniedError, match="explicit developer approval"):
        sign_task_record(
            task,
            identity=identity,
            account_id=42,
            workspace_id="workspace_primary",
            runner_kind="private_server",
            issued_at=NOW,
        )

    envelope = sign_task_record(
        task,
        identity=identity,
        account_id=42,
        workspace_id="workspace_primary",
        runner_kind="private_server",
        sensitive_approved=True,
        issued_at=NOW,
        nonce="fixed-private-server-nonce",
    )
    authorization = verify_authorized_job(
        envelope,
        public_key=identity.public_key,
        expected_target=ExecutionTarget.PRIVATE_SERVER,
        expected_runner_id="runner_server",
        now=NOW + timedelta(seconds=1),
    )
    assert "deployment:execute" in authorization["permissions"]


def test_legacy_cloud_target_must_be_assigned_to_a_private_runner() -> None:
    with pytest.raises(ControlPlaneError, match="explicit private_server runner"):
        execution_target_for_task(_task(execution_target="cloud"))


def test_unapproved_task_cannot_receive_execution_signature() -> None:
    with pytest.raises(ControlPlaneError, match="queued or atomically claimed"):
        sign_task_record(
            _task(status="awaiting_approval"),
            identity=_identity(),
            account_id=42,
            workspace_id="workspace_primary",
            runner_kind="local_computer",
        )


def test_runner_task_must_be_claimed_and_bound_to_the_correct_account() -> None:
    with pytest.raises(ControlPlaneError, match="atomically claimed"):
        sign_task_record(
            _task(status="queued"),
            identity=_identity(),
            account_id=42,
            workspace_id="workspace_primary",
            runner_kind="local_computer",
        )

    with pytest.raises(ControlPlaneError, match="different developer account"):
        sign_task_record(
            _task(account_id="99"),
            identity=_identity(),
            account_id=42,
            workspace_id="workspace_primary",
            runner_kind="local_computer",
        )


def test_github_job_requires_a_repository_binding() -> None:
    with pytest.raises(ControlPlaneError, match="bound to a repository"):
        sign_task_record(
            _task(
                execution_target="github",
                runner_id=None,
                repository=None,
                mode="review",
                delivery="report",
                status="queued",
            ),
            identity=_identity(),
            account_id=42,
            workspace_id="workspace_primary",
        )
