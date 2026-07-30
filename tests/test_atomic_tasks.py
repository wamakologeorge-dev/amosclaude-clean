"""Focused tests for governed Amosclaud atomic tasks."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from amoscloud_ai.atomic_tasks import (
    AtomicInstruction,
    AtomicTask,
    AtomicTaskError,
    AtomicTaskRegistry,
    docker_build_atom,
    run_autonomous_sequence,
)


class RecordingKernel:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "status": "planned",
            "evidence": ["Delegated through the canonical Autonomous kernel."],
        }


def test_atomic_task_requires_portable_name_and_supported_modes() -> None:
    with pytest.raises(ValidationError, match="portable lowercase"):
        AtomicTask(
            name="docker<build>",
            description="Invalid portable name.",
            action=lambda: {"objective": "Plan a build."},
        )

    with pytest.raises(ValidationError, match="unsupported autonomous modes"):
        AtomicTask(
            name="invalid_mode_atom",
            description="Invalid mode.",
            action=lambda: {"objective": "Plan a build."},
            allowed_modes=frozenset({"unknown"}),
        )


def test_atomic_task_validates_context_and_requested_mode() -> None:
    task = AtomicTask(
        name="inspect_atom",
        description="Inspects one repository path.",
        action=lambda path: {"objective": f"Inspect {path}", "mode": "plan"},
        required_context=frozenset({"path"}),
        allowed_modes=frozenset({"plan"}),
    )

    with pytest.raises(AtomicTaskError, match="missing context"):
        task.prepare({})

    instruction = task.prepare({"path": "src"})
    assert instruction == AtomicInstruction(objective="Inspect src", mode="plan")

    disallowed = AtomicTask(
        name="disallowed_atom",
        description="Requests a mode outside its declaration.",
        action=lambda: {"objective": "Write a file", "mode": "write"},
        allowed_modes=frozenset({"plan"}),
    )
    with pytest.raises(AtomicTaskError, match="disallowed mode"):
        disallowed.prepare({})


def test_atomic_registry_rejects_duplicates_and_returns_safe_manifests() -> None:
    registry = AtomicTaskRegistry((docker_build_atom,))

    with pytest.raises(AtomicTaskError, match="already registered"):
        registry.register(docker_build_atom)
    with pytest.raises(AtomicTaskError, match="unknown atomic task"):
        registry.get("missing_atom")

    manifest = registry.manifests()[0]
    assert manifest["name"] == "docker_build_atom"
    assert manifest["required_context"] == ["path"]
    assert manifest["allowed_modes"] == ["build"]
    assert manifest["write_capable"] is True
    assert "action" not in manifest


def test_docker_build_atom_prepares_a_real_build_request_without_fake_success() -> None:
    instruction = docker_build_atom.prepare({"path": "./amosclaud-clean"})

    assert instruction.mode == "build"
    assert "Build and verify a container image" in instruction.objective
    assert instruction.metadata == {
        "workspace_path": "./amosclaud-clean",
        "requested_artifact": "amosclaud-clean:latest",
    }


def test_autonomous_sequence_delegates_to_the_single_governed_kernel() -> None:
    kernel = RecordingKernel()

    result = run_autonomous_sequence(
        docker_build_atom,
        {"path": "./amosclaud-clean"},
        kernel=kernel,
        authorized_writes=False,
    )

    assert result["status"] == "planned"
    assert result["atomic_task"]["name"] == "docker_build_atom"
    assert len(kernel.calls) == 1
    call = kernel.calls[0]
    assert call["mode"] == "build"
    assert call["authorized_writes"] is False
    assert call["security_grant"] is None
    assert call["metadata"]["atomic_context_keys"] == ["path"]
    assert call["metadata"]["atomic_task"]["metadata"] == {
        "category": "container",
        "runtime": "amosclaud-autonomous",
    }
