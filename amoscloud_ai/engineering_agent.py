"""Compatibility engineering API backed by Amosclaud Autonomous.

This module preserves the older ``run_engineering_agent`` contract while
removing its independent model/write/test loop.  Planning, authorization,
repository access, repair, and verification now belong to the canonical
``AutonomousKernel``.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.amosclaud_os.kernel import get_autonomous_kernel


class EngineeringAgentError(RuntimeError):
    """Raised when a compatibility engineering request is invalid."""


@dataclass
class EngineeringChange:
    path: str
    status: str
    bytes_written: int = 0


@dataclass
class EngineeringRun:
    run_id: str
    objective: str
    workspace: str
    summary: str
    applied: bool
    changes: list[EngineeringChange] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


def _resolve_workspace(repository_root: Path, workspace_path: str | None) -> Path:
    root = repository_root.resolve()
    selected = (root / workspace_path).resolve() if workspace_path else root
    try:
        selected.relative_to(root)
    except ValueError as exc:
        raise EngineeringAgentError(
            "Workspace must remain inside the Amosclaud repository root"
        ) from exc
    if not selected.is_dir():
        raise EngineeringAgentError("Selected workspace folder does not exist")
    return selected


def _changes_from_result(result: dict[str, Any], applied: bool) -> list[EngineeringChange]:
    raw_paths = (
        result.get("changed_files")
        or result.get("files_changed")
        or result.get("artifacts")
        or []
    )
    changes: list[EngineeringChange] = []
    for item in raw_paths:
        if isinstance(item, dict):
            path = str(item.get("path") or item.get("name") or "").strip()
        else:
            path = str(item).strip()
        if path:
            changes.append(
                EngineeringChange(path=path, status="written" if applied else "planned")
            )
    return changes


def run_engineering_agent(
    repository_root: Path,
    objective: str,
    *,
    workspace_path: str | None = None,
    apply_changes: bool = False,
) -> EngineeringRun:
    """Submit engineering work to the one Amosclaud Autonomous kernel."""
    objective = " ".join((objective or "").split())
    if not objective:
        raise EngineeringAgentError("An engineering objective is required")

    workspace = _resolve_workspace(repository_root, workspace_path)
    kernel = get_autonomous_kernel(workspace)
    result = kernel.execute(
        objective=objective,
        mode="fix" if apply_changes else "plan",
        authorized_writes=apply_changes,
        metadata={
            "compatibility_entrypoint": "amoscloud_ai.engineering_agent",
            "repository_root": str(repository_root.resolve()),
        },
    )

    status = str(result.get("status") or "planned").lower()
    checks = list(result.get("checks") or result.get("tests") or [])
    if isinstance(result.get("tests"), dict):
        checks = [result["tests"]]
    evidence = list(result.get("evidence") or [])
    evidence.append(
        "Executed by src.amosclaud_os.kernel.AutonomousKernel; no independent engineering agent was created."
    )
    summary = str(
        result.get("summary")
        or result.get("message")
        or result.get("error")
        or f"Engineering request {status}."
    )

    return EngineeringRun(
        run_id=str(result.get("run_id") or result.get("verification_id") or uuid.uuid4().hex),
        objective=objective,
        workspace=str(workspace),
        summary=summary,
        applied=apply_changes and status not in {"blocked", "failed"},
        changes=_changes_from_result(result, apply_changes),
        checks=checks,
        evidence=evidence,
    )


__all__ = [
    "EngineeringAgentError",
    "EngineeringChange",
    "EngineeringRun",
    "run_engineering_agent",
]
