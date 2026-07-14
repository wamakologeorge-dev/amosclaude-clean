"""Autonomous repository runtime for the Amosclaud server.

The runtime is deterministic by default and does not require an AI agent.
An engineering agent can be enabled explicitly with metadata.use_agent=true.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from amoscloud_ai.models import PipelineStatus


SKIP_DIRS = {".git", ".pytest_cache", "__pycache__", "venv", ".venv", "node_modules"}
TEXT_SUFFIXES = {
    ".py",
    ".js",
    ".ts",
    ".html",
    ".css",
    ".md",
    ".yml",
    ".yaml",
    ".json",
    ".txt",
    ".sh",
}


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


@dataclass
class AutonomousRunResult:
    status: PipelineStatus
    reply: str
    checks: list[CheckResult]
    logs: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reply": self.reply,
            "checks": [
                {
                    "name": check.name,
                    "status": check.status,
                    "summary": check.summary,
                    "details": check.details,
                }
                for check in self.checks
            ],
            "logs": self.logs,
        }


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def run_autonomous_server(
    mode: str,
    objective: str,
    metadata: Optional[dict[str, Any]] = None,
) -> AutonomousRunResult:
    """Run repository operations without requiring an AI agent.

    Set ``metadata["use_agent"]`` to true to add the optional engineering
    agent step for build runs. If that optional component is unavailable, the
    core runtime continues with deterministic checks instead of crashing.
    """
    root = repo_root()
    metadata = metadata or {}
    use_agent = mode == "build" and bool(metadata.get("use_agent", False))
    checks: list[CheckResult] = []
    logs = [
        f"Amosclaud Autonomous Runtime: repo access confirmed at {root}",
        f"Mode: {mode}",
        f"Objective: {objective}",
        f"Executor: {'runtime + optional agent' if use_agent else 'runtime only'}",
    ]

    if use_agent:
        checks.extend(_run_optional_engineering_agent(root, objective, metadata))
    elif mode == "build":
        checks.append(
            CheckResult(
                name="build-runtime",
                status="passed",
                summary="Build is running through the autonomous runtime without an AI agent.",
                details=["Set metadata.use_agent=true only when AI-guided engineering is required."],
            )
        )

    checks.append(_git_status_check(root))
    checks.append(_conflict_marker_check(root))
    checks.append(_python_compile_check(root))

    if mode in {"autonomous-check", "build", "monitor"}:
        checks.append(_server_tests_check(root))

    failed = [check for check in checks if check.status == "failed"]
    warnings = [check for check in checks if check.status == "warning"]

    for check in checks:
        logs.append(f"{check.name}: {check.status} - {check.summary}")
        logs.extend(check.details[:10])

    if failed:
        status = PipelineStatus.FAILED
        reply = (
            "Amosclaud Autonomous Runtime: operation finished and needs action. "
            f"{len(failed)} blocking check(s) failed."
        )
    elif warnings:
        status = PipelineStatus.SUCCESS
        reply = (
            "Amosclaud Autonomous Runtime: operation completed with warnings. "
            "The runtime remains operational without an AI agent."
        )
    else:
        status = PipelineStatus.SUCCESS
        reply = (
            "Amosclaud Autonomous Runtime: repository scan, compile, and tests "
            "completed successfully without requiring an AI agent."
        )

    if metadata:
        logs.append(f"Metadata: {metadata}")

    return AutonomousRunResult(status=status, reply=reply, checks=checks, logs=logs)


def _run_optional_engineering_agent(
    root: Path,
    objective: str,
    metadata: dict[str, Any],
) -> list[CheckResult]:
    """Run the AI engineering layer only when explicitly requested."""
    try:
        from amoscloud_ai.engineering_agent import EngineeringAgentError, run_engineering_agent
    except (ImportError, ModuleNotFoundError) as exc:
        return [
            CheckResult(
                name="engineering-agent",
                status="warning",
                summary="Optional engineering agent is unavailable; autonomous runtime continued.",
                details=[str(exc)],
            )
        ]

    try:
        engineering = run_engineering_agent(
            root,
            objective,
            workspace_path=metadata.get("workspace_path"),
            apply_changes=bool(metadata.get("apply_changes", False)),
        )
    except EngineeringAgentError as exc:
        return [
            CheckResult(
                name="engineering-agent",
                status="warning",
                summary="Optional engineering agent stopped; autonomous runtime continued.",
                details=[str(exc)],
            )
        ]
    except Exception as exc:
        return [
            CheckResult(
                name="engineering-agent",
                status="warning",
                summary="Optional engineering agent failed; autonomous runtime continued safely.",
                details=[f"{type(exc).__name__}: {exc}"],
            )
        ]

    failed_agent_checks = [check for check in engineering.checks if not check.get("passed", False)]
    results = [
        CheckResult(
            name="engineering-agent",
            status="failed" if failed_agent_checks else "passed",
            summary=engineering.summary,
            details=[
                f"Run: {engineering.run_id}",
                f"Applied: {engineering.applied}",
                *[
                    f"{change.status}: {change.path} ({change.bytes_written} bytes)"
                    for change in engineering.changes
                ],
                *engineering.evidence,
            ],
        )
    ]
    for check in engineering.checks:
        results.append(
            CheckResult(
                name=f"engineering-{check['name']}",
                status="passed" if check.get("passed") else "failed",
                summary=f"{check['name']} {'passed' if check.get('passed') else 'failed'}.",
                details=str(check.get("output", "")).splitlines()[-30:],
            )
        )
    return results


def _run_command(root: Path, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=root,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _git_status_check(root: Path) -> CheckResult:
    if not (root / ".git").exists():
        return CheckResult(
            name="git-status",
            status="passed",
            summary="Git metadata is not included in the production container; repository files are available.",
        )

    try:
        result = _run_command(root, ["git", "status", "--short"], timeout=10)
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        return CheckResult(
            name="git-status",
            status="warning",
            summary="Git status is unavailable in this runtime.",
            details=[str(exc)],
        )

    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()
        if "not a git repository" in error.lower():
            return CheckResult(
                name="git-status",
                status="passed",
                summary="Production container has no Git metadata; repository files are available.",
            )
        return CheckResult(
            name="git-status",
            status="warning",
            summary="Unable to read repository status in this runtime.",
            details=[error],
        )

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    unmerged = [line for line in lines if line.startswith(("UU", "AA", "DD", "AU", "UA", "DU", "UD"))]
    if unmerged:
        return CheckResult(
            name="git-status",
            status="failed",
            summary=f"{len(unmerged)} unmerged file(s) need resolution.",
            details=unmerged,
        )
    if lines:
        return CheckResult(
            name="git-status",
            status="warning",
            summary=f"{len(lines)} changed file(s) in the workspace.",
            details=lines[:25],
        )
    return CheckResult(name="git-status", status="passed", summary="Workspace is clean.")


def _conflict_marker_check(root: Path) -> CheckResult:
    markers: list[str] = []
    for path in _iter_text_files(root):
        try:
            for number, line in enumerate(
                path.read_text(encoding="utf-8", errors="ignore").splitlines(),
                start=1,
            ):
                if line.startswith(("<<<<<<<", "=======", ">>>>>>>")):
                    markers.append(f"{path.relative_to(root)}:{number}: {line[:80]}")
                    break
        except OSError:
            continue

    if markers:
        return CheckResult(
            name="conflict-markers",
            status="failed",
            summary=f"{len(markers)} file(s) still contain merge conflict markers.",
            details=markers,
        )
    return CheckResult(name="conflict-markers", status="passed", summary="No conflict markers found.")


def _python_compile_check(root: Path) -> CheckResult:
    files = [
        "amoscloud_ai/api/routes/agent.py",
        "amoscloud_ai/api/routes/copilot.py",
        "amoscloud_ai/autonomous_server.py",
        "amoscloud_ai/main.py",
        "amoscloud_ai/models.py",
        "amoscloud_ai/worker.py",
    ]
    existing = [str(root / file_path) for file_path in files if (root / file_path).exists()]
    result = _run_command(root, [sys.executable, "-m", "py_compile", *existing], timeout=30)
    if result.returncode != 0:
        return CheckResult(
            name="python-compile",
            status="failed",
            summary="Python compile check failed.",
            details=(result.stderr or result.stdout).splitlines()[:20],
        )
    return CheckResult(name="python-compile", status="passed", summary=f"Compiled {len(existing)} key module(s).")


def _server_tests_check(root: Path) -> CheckResult:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return CheckResult(
            name="server-tests",
            status="warning",
            summary="Skipped nested pytest run while endpoint tests are already executing.",
        )

    python_bin = root / "venv" / "bin" / "python"
    executable = str(python_bin) if python_bin.exists() else sys.executable
    result = _run_command(root, [executable, "-m", "pytest", "tests/test_server.py"], timeout=60)
    output = (result.stdout + "\n" + result.stderr).splitlines()
    if result.returncode != 0:
        return CheckResult(
            name="server-tests",
            status="failed",
            summary="Focused server tests failed.",
            details=output[-30:],
        )
    summary = next((line for line in reversed(output) if " passed" in line), "Focused server tests passed.")
    return CheckResult(name="server-tests", status="passed", summary=summary)


def _iter_text_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES:
            yield path
