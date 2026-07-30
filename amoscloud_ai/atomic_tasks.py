"""Composable, governed execution units for Amosclaud Autonomous.

Atomic tasks are declarative building blocks. Their actions prepare a bounded
instruction, while the canonical AutonomousKernel remains responsible for
planning, authorization, execution, verification, and truthful reporting.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.amosclaud_os.kernel import get_autonomous_kernel

SUPPORTED_MODES = frozenset(
    {
        "answer",
        "build",
        "create",
        "deploy",
        "fix",
        "guide",
        "learn",
        "plan",
        "react",
        "teach",
        "write",
    }
)
WRITE_MODES = frozenset({"build", "create", "deploy", "fix", "write"})
_ATOM_NAME = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")

AtomicAction = Callable[..., Mapping[str, Any] | "AtomicInstruction"]


class AtomicTaskError(RuntimeError):
    """Raised when an atomic definition or invocation is invalid."""


class AtomicInstruction(BaseModel):
    """Declarative work request produced by an atomic action."""

    model_config = ConfigDict(frozen=True)

    objective: str
    mode: str = "plan"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("objective")
    @classmethod
    def validate_objective(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("objective must not be empty")
        return normalized

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_MODES:
            raise ValueError(f"unsupported autonomous mode: {normalized}")
        return normalized


class AtomicTask(BaseModel):
    """One reusable task definition consumed by Amosclaud Autonomous."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    name: str
    description: str
    action: AtomicAction = Field(exclude=True, repr=False)
    required_context: frozenset[str] = Field(default_factory=frozenset)
    allowed_modes: frozenset[str] = Field(default_factory=lambda: frozenset({"plan"}))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _ATOM_NAME.fullmatch(normalized):
            raise ValueError("name must use portable lowercase identifier characters")
        return normalized

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("description must not be empty")
        return normalized

    @field_validator("required_context")
    @classmethod
    def validate_required_context(cls, value: frozenset[str]) -> frozenset[str]:
        invalid = sorted(key for key in value if not key or not key.isidentifier())
        if invalid:
            raise ValueError(f"invalid context keys: {', '.join(invalid)}")
        return value

    @field_validator("allowed_modes")
    @classmethod
    def validate_allowed_modes(cls, value: frozenset[str]) -> frozenset[str]:
        normalized = frozenset(mode.strip().lower() for mode in value)
        invalid = sorted(normalized - SUPPORTED_MODES)
        if invalid:
            raise ValueError(f"unsupported autonomous modes: {', '.join(invalid)}")
        if not normalized:
            raise ValueError("allowed_modes must not be empty")
        return normalized

    @property
    def write_capable(self) -> bool:
        """Return whether this atom can request a write-capable kernel mode."""

        return bool(self.allowed_modes & WRITE_MODES)

    def prepare(self, context: Mapping[str, Any]) -> AtomicInstruction:
        """Validate context and build a declarative Autonomous instruction."""

        prepared = dict(context)
        missing = sorted(self.required_context - prepared.keys())
        if missing:
            raise AtomicTaskError(f"missing context for {self.name}: {', '.join(missing)}")
        try:
            raw_instruction = self.action(**prepared)
            instruction = (
                raw_instruction
                if isinstance(raw_instruction, AtomicInstruction)
                else AtomicInstruction.model_validate(raw_instruction)
            )
        except AtomicTaskError:
            raise
        except Exception as exc:
            raise AtomicTaskError(f"atomic action {self.name} could not prepare its instruction") from exc
        if instruction.mode not in self.allowed_modes:
            raise AtomicTaskError(
                f"atomic action {self.name} requested disallowed mode {instruction.mode}"
            )
        return instruction

    def manifest(self) -> dict[str, Any]:
        """Return serializable discovery metadata without exposing the callable."""

        return {
            "name": self.name,
            "description": self.description,
            "required_context": sorted(self.required_context),
            "allowed_modes": sorted(self.allowed_modes),
            "write_capable": self.write_capable,
            "metadata": dict(self.metadata),
        }


class AtomicTaskRegistry:
    """In-process registry for trusted, code-defined atomic tasks."""

    def __init__(self, tasks: Iterable[AtomicTask] = ()) -> None:
        self._tasks: dict[str, AtomicTask] = {}
        for task in tasks:
            self.register(task)

    def register(self, task: AtomicTask) -> AtomicTask:
        if task.name in self._tasks:
            raise AtomicTaskError(f"atomic task already registered: {task.name}")
        self._tasks[task.name] = task
        return task

    def get(self, name: str) -> AtomicTask:
        normalized = name.strip().lower()
        try:
            return self._tasks[normalized]
        except KeyError as exc:
            raise AtomicTaskError(f"unknown atomic task: {normalized}") from exc

    def manifests(self) -> list[dict[str, Any]]:
        return [self._tasks[name].manifest() for name in sorted(self._tasks)]


def run_autonomous_sequence(
    task: AtomicTask,
    context: Mapping[str, Any],
    *,
    workspace: Path | str = ".",
    authorized_writes: bool = False,
    security_grant: str | None = None,
    kernel: Any | None = None,
) -> dict[str, Any]:
    """Execute one atom through the canonical governed Autonomous runtime.

    The atom only prepares an instruction. Write-capable modes remain subject to
    the kernel's signed capability chain and cannot be authorized by the atom.
    """

    instruction = task.prepare(context)
    runtime = kernel or get_autonomous_kernel(workspace)
    result = runtime.execute(
        objective=instruction.objective,
        mode=instruction.mode,
        authorized_writes=authorized_writes,
        security_grant=security_grant,
        metadata={
            **instruction.metadata,
            "atomic_task": task.manifest(),
            "atomic_context_keys": sorted(context.keys()),
        },
    )
    if not isinstance(result, dict):
        raise AtomicTaskError("Autonomous kernel returned an invalid result")
    return {**result, "atomic_task": task.manifest()}


def _docker_build_instruction(*, path: str) -> dict[str, Any]:
    normalized = str(path or "").strip().replace("\\", "/")
    if not normalized or "\x00" in normalized:
        raise AtomicTaskError("path must identify a workspace")
    workspace_name = Path(normalized.rstrip("/")).name or "workspace"
    return {
        "objective": (
            f"Build and verify a container image from workspace path {normalized}. "
            "Report the real image artifact and build evidence."
        ),
        "mode": "build",
        "metadata": {
            "workspace_path": normalized,
            "requested_artifact": f"{workspace_name}:latest",
        },
    }


docker_build_atom = AtomicTask(
    name="docker_build_atom",
    description="Builds and verifies a container image from an approved workspace path.",
    action=_docker_build_instruction,
    required_context=frozenset({"path"}),
    allowed_modes=frozenset({"build"}),
    metadata={"category": "container", "runtime": "amosclaud-autonomous"},
)

DEFAULT_ATOMIC_TASKS = AtomicTaskRegistry((docker_build_atom,))

__all__ = [
    "AtomicInstruction",
    "AtomicTask",
    "AtomicTaskError",
    "AtomicTaskRegistry",
    "DEFAULT_ATOMIC_TASKS",
    "docker_build_atom",
    "run_autonomous_sequence",
]
