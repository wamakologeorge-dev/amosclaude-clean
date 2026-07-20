"""Governed engineering compatibility API for Amosclaud Autonomous.

This module preserves the original engineering-agent interface while keeping
workspace validation, protected-path checks, atomic writes, backups, memory,
and verification in one bounded implementation.  It is a compatibility layer,
not a second autonomous decision-making runtime.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from amoscloud_ai import provider
from amoscloud_ai.agent_memory import AgentMemory
from src.amosclaud_os.kernel import get_autonomous_kernel

PROTECTED_PARTS = {
    ".git",
    ".amosclaud",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "data",
}
ALLOWED_SUFFIXES = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".json",
    ".md",
    ".yml",
    ".yaml",
    ".toml",
    ".sh",
}
MAX_CONTEXT_FILES = 24
MAX_CHANGES = 12
MAX_TOTAL_WRITE_BYTES = 1_000_000


class EngineeringAgentError(RuntimeError):
    """Raised when a governed engineering request is invalid or unsafe."""


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


def _workspace(root: Path | str, requested: str | None = None) -> Path:
    """Resolve a workspace and prevent traversal outside the repository root."""
    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        raise EngineeringAgentError("Selected repository root does not exist")
    selected = (base / requested).resolve() if requested else base
    try:
        selected.relative_to(base)
    except ValueError as exc:
        raise EngineeringAgentError(
            "Workspace must remain inside the Amosclaud folder"
        ) from exc
    if not selected.is_dir():
        raise EngineeringAgentError("Selected workspace folder does not exist")
    return selected


def _validate_change(root: Path, item: Any) -> tuple[Path, str]:
    """Validate one complete-file change before any filesystem mutation."""
    if not isinstance(item, dict):
        raise EngineeringAgentError("Every change must be an object")
    raw_path = str(item.get("path", "")).strip().replace("\\", "/")
    content = item.get("content")
    if not raw_path or not isinstance(content, str):
        raise EngineeringAgentError(
            "Every change requires a path and complete text content"
        )
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise EngineeringAgentError("Change path escapes the workspace")
    if any(part in PROTECTED_PARTS or part.startswith(".env") for part in relative.parts):
        raise EngineeringAgentError(f"Protected path cannot be changed: {raw_path}")
    if relative.suffix.lower() not in ALLOWED_SUFFIXES:
        raise EngineeringAgentError(f"Unsupported file type: {raw_path}")
    target = (root / relative).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise EngineeringAgentError("Change path escapes the workspace") from exc
    if target.exists() and target.is_symlink():
        raise EngineeringAgentError("Symbolic links cannot be edited")
    return target, content


def _checks(root: Path, changes: list[EngineeringChange]) -> list[dict[str, Any]]:
    """Verification extension point used by the canonical test runner."""
    del root, changes
    return []


def _parse_plan(reply: str) -> dict[str, Any]:
    candidate = reply.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines.pop()
        candidate = "\n".join(lines)
    try:
        plan = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise EngineeringAgentError(
            "Model did not return a valid structured change plan"
        ) from exc
    if not isinstance(plan, dict) or not isinstance(plan.get("changes", []), list):
        raise EngineeringAgentError("Model change plan has an invalid structure")
    return plan


def _apply(root: Path, run_id: str, raw_changes: list[Any]) -> list[EngineeringChange]:
    if len(raw_changes) > MAX_CHANGES:
        raise EngineeringAgentError(
            f"Change plan exceeds the {MAX_CHANGES}-file limit"
        )
    validated = [_validate_change(root, item) for item in raw_changes]
    total_bytes = sum(len(content.encode("utf-8")) for _, content in validated)
    if total_bytes > MAX_TOTAL_WRITE_BYTES:
        raise EngineeringAgentError("Change plan exceeds the write-size limit")

    results: list[EngineeringChange] = []
    backup_root = root / ".amosclaud" / "backups" / run_id
    for target, content in validated:
        relative = target.relative_to(root)
        if target.exists():
            backup = backup_root / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(target.read_bytes())
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=target.parent, delete=False
        ) as stream:
            stream.write(content)
            temporary = Path(stream.name)
        os.replace(temporary, target)
        results.append(
            EngineeringChange(
                relative.as_posix(), "written", len(content.encode("utf-8"))
            )
        )
    return results


def _source_context(root: Path) -> tuple[str, list[str]]:
    files = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in ALLOWED_SUFFIXES
        and not any(part in PROTECTED_PARTS for part in path.relative_to(root).parts)
    ][:MAX_CONTEXT_FILES]
    paths = [path.relative_to(root).as_posix() for path in files]
    context = "\n\n".join(
        f"FILE: {relative}\n{path.read_text(encoding='utf-8', errors='replace')}"
        for path, relative in zip(files, paths)
    )
    return context, paths


def run_engineering_agent(
    repository_root: Path | str,
    objective: str,
    *,
    workspace_path: str | None = None,
    apply_changes: bool = False,
) -> EngineeringRun:
    """Plan or apply bounded repository work through Amosclaud's model provider."""
    objective = " ".join((objective or "").split())
    if not objective:
        raise EngineeringAgentError("An engineering objective is required")

    root = _workspace(repository_root, workspace_path)
    run_id = uuid.uuid4().hex
    memory = AgentMemory.for_repository(root)
    recalled = memory.recall(objective)
    context, paths = _source_context(root)

    # New repositories are valid workspaces.  Planning must be able to propose
    # their first file; applying still passes every proposed path through the
    # same protected-path and suffix validation below.
    repository_context = context or "The repository is currently empty. Propose only essential starter files."
    result = provider.reply(
        [
            {
                "role": "user",
                "content": (
                    f"Objective: {objective}\n"
                    "Return JSON with summary and changes.\n"
                    f"Available paths: {json.dumps(paths)}\n"
                    f"{repository_context}"
                ),
            }
        ],
        "Return a safe, minimal, structured engineering change plan. Output JSON only.",
    )
    if result.status != "ready":
        # The canonical kernel remains available for an offline plan; this also
        # keeps compatibility callers on the single Autonomous runtime.
        kernel_result = get_autonomous_kernel(root).execute(
            objective=objective,
            mode="build" if apply_changes else "plan",
            authorized_writes=apply_changes,
            metadata={"compatibility_entrypoint": "engineering_agent"},
        )
        changed = list(kernel_result.get("changed_files") or [])
        changes = [EngineeringChange(str(item), "written" if apply_changes else "planned") for item in changed]
        return EngineeringRun(
            run_id=str(kernel_result.get("run_id") or run_id), objective=objective,
            workspace=str(root), summary=str(kernel_result.get("summary") or "Engineering plan prepared"),
            applied=apply_changes, changes=changes,
            checks=list(kernel_result.get("checks") or []),
            evidence=["Runtime: src.amosclaud_os.kernel.AutonomousKernel", *list(kernel_result.get("evidence") or [])],
        )

    plan = _parse_plan(result.reply)
    raw_changes = plan.get("changes", [])
    if apply_changes:
        changes = _apply(root, run_id, raw_changes)
        checks = _checks(root, changes)
    else:
        changes = [
            EngineeringChange(
                str(item.get("path", "")),
                "planned",
                len(str(item.get("content", "")).encode("utf-8")),
            )
            for item in raw_changes
            if isinstance(item, dict)
        ]
        checks = []

    summary = str(plan.get("summary", "Engineering plan prepared")).strip()
    memory.remember(
        kind="engineering-run",
        title=f"Engineering lesson {run_id[:8]}",
        content=(
            f"Outcome: {summary}; mode: "
            f"{'applied' if apply_changes else 'planned'}; "
            f"files: {', '.join(change.path for change in changes) or 'none'}."
        ),
        tags=["engineering", "applied" if apply_changes else "planned"],
        importance=0.7,
        source_run_id=run_id,
    )
    memory.consolidate_day()

    return EngineeringRun(
        run_id=run_id,
        objective=objective,
        workspace=str(root),
        summary=summary,
        applied=apply_changes,
        changes=changes,
        checks=checks,
        evidence=[
            f"Inspected {len(paths)} supported source files.",
            f"Runtime: {result.runtime}",
            f"Recalled {len(recalled)} relevant memories; stored a new lesson.",
        ],
    )


class EngineeringAgent:
    """Object-oriented facade for callers that previously instantiated an agent."""

    def __init__(self, workspace: Path | str) -> None:
        self.workspace = _workspace(workspace)

    def plan(self, objective: str) -> EngineeringRun:
        return run_engineering_agent(
            self.workspace,
            objective,
            apply_changes=False,
        )

    def apply(self, objective: str) -> EngineeringRun:
        return run_engineering_agent(
            self.workspace,
            objective,
            apply_changes=True,
        )


__all__ = [
    "EngineeringAgent",
    "EngineeringAgentError",
    "EngineeringChange",
    "EngineeringRun",
    "provider",
    "_workspace",
    "_validate_change",
    "_checks",
    "run_engineering_agent",
]
