"""Bridge existing Amosclaud task records into signed Control Plane jobs."""

from __future__ import annotations

from typing import Any, Mapping

from amoscloud_ai.control_plane import (
    ControlPlaneError,
    ControlPlaneIdentity,
    ExecutionTarget,
)

RUNNER_KINDS = frozenset({"local_computer", "private_server"})

TASK_MODE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "ask": ("repository:read", "workspace:read", "logs:write"),
    "review": ("repository:read", "workspace:read", "logs:write"),
    "monitor": ("monitoring:read", "logs:write"),
    "test": (
        "repository:read",
        "workspace:read",
        "tests:run",
        "logs:write",
        "artifacts:write",
    ),
    "build": (
        "repository:read",
        "workspace:read",
        "workspace:write",
        "tests:run",
        "patch:create",
        "logs:write",
        "artifacts:write",
    ),
    "fix": (
        "repository:read",
        "workspace:read",
        "workspace:write",
        "tests:run",
        "patch:create",
        "logs:write",
        "artifacts:write",
    ),
    "deploy": (
        "repository:read",
        "workspace:read",
        "deployment:prepare",
        "deployment:execute",
        "logs:write",
        "artifacts:write",
    ),
}

DELIVERY_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "report": (),
    "patch": ("patch:create",),
    "pull_request": ("patch:create", "github:pull_request:create"),
}


def execution_target_for_task(
    task: Mapping[str, Any],
    *,
    runner_kind: str | None = None,
) -> ExecutionTarget:
    """Translate current task-router targets into the native Control Plane model."""

    raw_target = str(task.get("execution_target") or "").strip()
    if raw_target == "github":
        return ExecutionTarget.GITHUB_REPOSITORY
    if raw_target == "self_hosted":
        normalized_kind = str(runner_kind or "").strip()
        if normalized_kind not in RUNNER_KINDS:
            raise ControlPlaneError(
                "self-hosted tasks require runner_kind=local_computer or private_server"
            )
        return ExecutionTarget(normalized_kind)
    if raw_target == "cloud":
        raise ControlPlaneError(
            "legacy cloud jobs must be assigned to an explicit private_server runner"
        )
    raise ControlPlaneError(f"unsupported task execution target: {raw_target or '<empty>'}")


def permissions_for_task(task: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the smallest known capability set for a task mode and delivery."""

    mode = str(task.get("mode") or "").strip()
    delivery = str(task.get("delivery") or "report").strip()
    try:
        mode_permissions = TASK_MODE_PERMISSIONS[mode]
    except KeyError as exc:
        raise ControlPlaneError(f"unsupported task mode: {mode or '<empty>'}") from exc
    try:
        delivery_permissions = DELIVERY_PERMISSIONS[delivery]
    except KeyError as exc:
        raise ControlPlaneError(
            f"unsupported task delivery: {delivery or '<empty>'}"
        ) from exc
    return tuple(sorted(set(mode_permissions) | set(delivery_permissions)))


def sign_task_record(
    task: Mapping[str, Any],
    *,
    identity: ControlPlaneIdentity,
    account_id: int | str,
    workspace_id: str,
    runner_kind: str | None = None,
    sensitive_approved: bool = False,
    ttl_seconds: int = 300,
) -> dict[str, Any]:
    """Create the executable authorization for one approved Amosclaud task."""

    status = str(task.get("status") or "").strip()
    if status not in {"queued", "running"}:
        raise ControlPlaneError(
            "only queued or atomically claimed tasks may receive an execution signature"
        )

    target = execution_target_for_task(task, runner_kind=runner_kind)
    permissions = permissions_for_task(task)
    request = {
        "mode": str(task.get("mode") or ""),
        "delivery": str(task.get("delivery") or ""),
        "metadata": dict(task.get("metadata") or {}),
        "bucket_id": task.get("bucket_id"),
    }

    return identity.authorize_job(
        job_id=str(task.get("id") or ""),
        account_id=account_id,
        workspace_id=workspace_id,
        target=target,
        objective=str(task.get("objective") or ""),
        permissions=permissions,
        request=request,
        repository=str(task.get("repository") or "").strip() or None,
        runner_id=str(task.get("runner_id") or "").strip() or None,
        sensitive_approved=sensitive_approved,
        ttl_seconds=ttl_seconds,
    )
