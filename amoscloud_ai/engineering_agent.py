"""Compatibility engineering API backed by governed Amosclaud operations."""
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

PROTECTED_PARTS = {".git", ".amosclaud", ".venv", "venv", "node_modules", "__pycache__", "data"}
ALLOWED_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".json", ".md", ".yml", ".yaml", ".toml", ".sh"}


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


def _workspace(root: Path, requested: str | None) -> Path:
    base = root.resolve()
    selected = (base / requested).resolve() if requested else base
    try:
        selected.relative_to(base)
    except ValueError as exc:
        raise EngineeringAgentError("Workspace must remain inside the Amosclaud folder") from exc
    if not selected.is_dir():
        raise EngineeringAgentError("Selected workspace folder does not exist")
    return selected


def _validate_change(root: Path, item: Any) -> tuple[Path, str]:
    if not isinstance(item, dict):
        raise EngineeringAgentError("Every change must be an object")
    raw_path = str(item.get("path", "")).strip().replace("\\", "/")
    content = item.get("content")
    if not raw_path or not isinstance(content, str):
        raise EngineeringAgentError("Every change requires a path and complete text content")
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
        raise EngineeringAgentError("Model did not return a valid structured change plan") from exc
    if not isinstance(plan, dict) or not isinstance(plan.get("changes", []), list):
        raise EngineeringAgentError("Model change plan has an invalid structure")
    return plan


def _apply(root: Path, run_id: str, raw_changes: list[Any]) -> list[EngineeringChange]:
    if len(raw_changes) > 12:
        raise EngineeringAgentError("Change plan exceeds the 12-file limit")
    validated = [_validate_change(root, item) for item in raw_changes]
    results: list[EngineeringChange] = []
    backup_root = root / ".amosclaud" / "backups" / run_id
    for target, content in validated:
        relative = target.relative_to(root)
        if target.exists():
            backup = backup_root / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(target.read_bytes())
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as stream:
            stream.write(content)
            temporary = Path(stream.name)
        os.replace(temporary, target)
        results.append(EngineeringChange(relative.as_posix(), "written", len(content.encode())))
    return results


def run_engineering_agent(
    repository_root: Path,
    objective: str,
    *,
    workspace_path: str | None = None,
    apply_changes: bool = False,
) -> EngineeringRun:
    objective = " ".join((objective or "").split())
    if not objective:
        raise EngineeringAgentError("An engineering objective is required")
    root = _workspace(repository_root, workspace_path)
    run_id = uuid.uuid4().hex
    memory = AgentMemory.for_repository(root)
    recalled = memory.recall(objective)
    files = [path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in ALLOWED_SUFFIXES]
    if not files:
        raise EngineeringAgentError("No supported source files were found in the selected folder")
    context = "\n\n".join(
        f"FILE: {path.relative_to(root).as_posix()}\n{path.read_text(encoding='utf-8', errors='replace')}"
        for path in files[:24]
    )
    result = provider.reply(
        [{"role": "user", "content": f"Objective: {objective}\nReturn JSON with summary and changes.\n{context}"}],
        "Return a safe, minimal, structured engineering change plan. Output JSON only.",
    )
    if result.status != "ready":
        raise EngineeringAgentError("Amosclaud model runtime is not ready")
    plan = _parse_plan(result.reply)
    raw_changes = plan.get("changes", [])
    if apply_changes:
        changes = _apply(root, run_id, raw_changes)
        checks = _checks(root, changes)
    else:
        changes = [
            EngineeringChange(str(item.get("path", "")), "planned", len(str(item.get("content", "")).encode()))
            for item in raw_changes if isinstance(item, dict)
        ]
        checks = []
    summary = str(plan.get("summary", "Engineering plan prepared")).strip()
    memory.remember(
        kind="engineering-run",
        title=f"Engineering lesson {run_id[:8]}",
        content=f"Outcome: {summary}; mode: {'applied' if apply_changes else 'planned'}.",
        tags=["engineering"],
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
        evidence=[f"Runtime: {result.runtime}", f"Recalled {len(recalled)} relevant memories; stored a new lesson."],
    )


__all__ = [
    "EngineeringAgentError", "EngineeringChange", "EngineeringRun", "provider",
    "_workspace", "_validate_change", "_checks", "run_engineering_agent",
]
