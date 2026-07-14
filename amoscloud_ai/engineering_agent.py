"""Controlled engineering loop for the folder-first Amosclaud agent."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from amoscloud_ai import provider

SKIP_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", "data"}
SOURCE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".json", ".md", ".yml", ".yaml", ".toml", ".sh"}
MAX_CONTEXT_FILES = 24
MAX_FILE_BYTES = 80_000
MAX_CHANGES = 12
MAX_TOTAL_WRITE_BYTES = 1_000_000


class EngineeringAgentError(RuntimeError):
    pass


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


def _within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _workspace(root: Path, requested: str | None) -> Path:
    base = root.resolve()
    candidate = (base / requested).resolve() if requested else base
    if not _within(base, candidate):
        raise EngineeringAgentError("Workspace must remain inside the Amosclaud folder")
    if not candidate.is_dir():
        raise EngineeringAgentError("Selected workspace folder does not exist")
    return candidate


def _source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if len(files) >= MAX_CONTEXT_FILES:
            break
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        relative = path.relative_to(root)
        if any(part in SKIP_PARTS for part in relative.parts):
            continue
        try:
            if path.stat().st_size <= MAX_FILE_BYTES:
                files.append(path)
        except OSError:
            continue
    return files


def _context(root: Path) -> tuple[str, list[str]]:
    sections: list[str] = []
    paths: list[str] = []
    for path in _source_files(root):
        relative = path.relative_to(root).as_posix()
        paths.append(relative)
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        sections.append(f"FILE: {relative}\n{content}")
    return "\n\n".join(sections), paths


def _parse_plan(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines)
    try:
        plan = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise EngineeringAgentError("Model did not return a valid structured change plan") from exc
    if not isinstance(plan, dict) or not isinstance(plan.get("changes", []), list):
        raise EngineeringAgentError("Model change plan has an invalid structure")
    return plan


def _prompt(objective: str, context: str, paths: list[str]) -> str:
    return f"""You are the Amosclaud engineering agent operating inside one folder.
Objective: {objective}

Return only valid JSON with this shape:
{{
  "summary": "short outcome",
  "changes": [
    {{"path": "relative/file.ext", "content": "complete replacement file content", "reason": "why"}}
  ]
}}

Rules:
- Use only paths already listed unless a new file is essential.
- Never edit secrets, .env files, .git, dependencies, generated files, or data.
- Make the smallest coherent change.
- Do not claim tests passed.
- Maximum {MAX_CHANGES} changed files.
- If no safe change is possible, return an empty changes list and explain why.

Available paths:
{json.dumps(paths)}

Repository context:
{context}
"""


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
    if any(part in SKIP_PARTS or part.startswith(".env") for part in relative.parts):
        raise EngineeringAgentError(f"Protected path cannot be changed: {raw_path}")
    if relative.suffix.lower() not in SOURCE_SUFFIXES:
        raise EngineeringAgentError(f"Unsupported file type: {raw_path}")
    target = (root / relative).resolve()
    if not _within(root, target):
        raise EngineeringAgentError("Change path escapes the workspace")
    if target.exists() and target.is_symlink():
        raise EngineeringAgentError("Symbolic links cannot be edited")
    return target, content


def _apply(root: Path, run_id: str, raw_changes: list[Any]) -> list[EngineeringChange]:
    if len(raw_changes) > MAX_CHANGES:
        raise EngineeringAgentError(f"Change plan exceeds the {MAX_CHANGES}-file limit")
    validated = [_validate_change(root, item) for item in raw_changes]
    if sum(len(content.encode()) for _, content in validated) > MAX_TOTAL_WRITE_BYTES:
        raise EngineeringAgentError("Change plan exceeds the write-size limit")

    backup_root = root / ".amosclaud" / "backups" / run_id
    results: list[EngineeringChange] = []
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


def _checks(root: Path, changes: list[EngineeringChange]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    python_files = [str(root / change.path) for change in changes if change.path.endswith(".py")]
    if python_files:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", *python_files],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        checks.append({
            "name": "python-compile",
            "passed": result.returncode == 0,
            "output": (result.stderr or result.stdout)[-4000:],
        })
    if (root / "tests").is_dir():
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        checks.append({
            "name": "pytest",
            "passed": result.returncode == 0,
            "output": (result.stdout + "\n" + result.stderr)[-6000:],
        })
    return checks


def _diff(root: Path) -> list[str]:
    if not (root / ".git").exists():
        return ["Git metadata is unavailable; written-file evidence is reported instead."]
    result = subprocess.run(
        ["git", "diff", "--stat", "--", "."],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return [line for line in result.stdout.splitlines() if line.strip()][:50]


def run_engineering_agent(
    repository_root: Path,
    objective: str,
    *,
    workspace_path: str | None = None,
    apply_changes: bool = False,
) -> EngineeringRun:
    run_id = uuid.uuid4().hex
    root = _workspace(repository_root, workspace_path)
    context, paths = _context(root)
    if not paths:
        raise EngineeringAgentError("No supported source files were found in the selected folder")

    result = provider.reply(
        [{"role": "user", "content": _prompt(objective, context, paths)}],
        "Return a safe, minimal, structured engineering change plan. Output JSON only.",
    )
    if result.status != "ready":
        raise EngineeringAgentError("Amosclaud model runtime is not ready")
    plan = _parse_plan(result.reply)
    raw_changes = plan.get("changes", [])
    summary = str(plan.get("summary", "Engineering plan prepared")).strip()

    changes: list[EngineeringChange] = []
    checks: list[dict[str, Any]] = []
    evidence = [f"Inspected {len(paths)} source files.", f"Runtime: {result.runtime}"]
    if apply_changes:
        changes = _apply(root, run_id, raw_changes)
        checks = _checks(root, changes)
        evidence.extend(_diff(root))
    else:
        changes = [
            EngineeringChange(str(item.get("path", "")), "planned", len(str(item.get("content", "")).encode()))
            for item in raw_changes
            if isinstance(item, dict)
        ]
        evidence.append("Plan-only mode: no files were written.")

    return EngineeringRun(
        run_id=run_id,
        objective=objective,
        workspace=str(root),
        summary=summary,
        applied=apply_changes,
        changes=changes,
        checks=checks,
        evidence=evidence,
    )
