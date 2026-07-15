"""Autonomous repository runtime and Agentic Cloud Engine adapter."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from amoscloud_ai.models import PipelineStatus

SKIP_DIRS = {".git", ".pytest_cache", "__pycache__", "venv", ".venv", "node_modules", ".amosclaud"}
TEXT_SUFFIXES = {".py", ".js", ".ts", ".html", ".css", ".md", ".yml", ".yaml", ".json", ".txt", ".sh"}
RUNTIME_PREFIX = "Amosclaud Autonomous Runtime:"


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
                {"name": item.name, "status": item.status, "summary": item.summary, "details": item.details}
                for item in self.checks
            ],
            "logs": self.logs,
        }


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def run_autonomous_server(mode: str, objective: str, metadata: Optional[dict[str, Any]] = None) -> AutonomousRunResult:
    root = repo_root()
    metadata = dict(metadata or {})

    # Build, review, monitor, and test operations must remain available even when
    # the planning model station is offline. Only an explicitly authorized fix
    # requires the five-engine model-guided write path.
    use_agent = mode == "fix"
    checks: list[CheckResult] = []
    logs = [
        f"Amosclaud Autonomous Cloud Agent: repository access confirmed at {root}",
        f"Mode: {mode}",
        f"Objective: {objective}",
        f"Executor: {'five-engine agentic core' if use_agent else 'deterministic runtime'}",
    ]

    if use_agent:
        checks.extend(_run_agentic_cloud_core(root, objective, mode, metadata))
    elif mode == "build":
        checks.append(
            CheckResult(
                "build-runtime",
                "passed",
                "Deterministic build inspection is running without requiring the model station.",
            )
        )

    checks.extend([_git_status_check(root), _conflict_marker_check(root), _python_compile_check(root)])
    if mode in {"autonomous-check", "build", "fix", "monitor"}:
        checks.append(_server_tests_check(root))

    for check in checks:
        logs.append(f"{check.name}: {check.status} - {check.summary}")
        logs.extend(check.details[:20])

    failed = [check for check in checks if check.status == "failed"]
    warnings = [check for check in checks if check.status == "warning"]
    if failed:
        return AutonomousRunResult(
            PipelineStatus.FAILED,
            f"{RUNTIME_PREFIX} {len(failed)} blocking check(s) failed. Review the exact evidence below.",
            checks,
            logs,
        )
    reply = f"{RUNTIME_PREFIX} completed the objective with verification evidence."
    if warnings:
        reply = f"{RUNTIME_PREFIX} completed the objective with warnings and evidence."
    return AutonomousRunResult(PipelineStatus.SUCCESS, reply, checks, logs)


def _run_agentic_cloud_core(root: Path, objective: str, mode: str, metadata: dict[str, Any]) -> list[CheckResult]:
    try:
        from amoscloud_ai.agentic_cloud_engine import run_agentic_cloud_engine

        run = run_agentic_cloud_engine(root, objective, mode, metadata)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        return [
            CheckResult(
                "agentic-cloud-core",
                "failed",
                "The authorized fix engine stopped safely before writing files.",
                [detail, "Configure a ready Amosclaud model station before running Fix mode."],
            )
        ]

    results = [
        CheckResult(
            "agentic-cloud-core",
            "passed" if run.status == "success" else "failed",
            run.summary,
            [
                f"Run: {run.run_id}",
                f"Write authorization: {run.authorized_writes}",
                *[f"Plan: {step}" for step in run.plan],
                *[f"Changed: {path}" for path in run.changed_files],
                *run.memory,
            ],
        )
    ]
    for event in run.events:
        results.append(
            CheckResult(event.engine, event.status, event.message, [f"Log service: {event.log_service}", *event.evidence])
        )
    for check in run.checks:
        results.append(
            CheckResult(
                f"agent-{check.get('name', 'verification')}",
                "passed" if check.get("passed") else "failed",
                f"{check.get('name', 'verification')} {'passed' if check.get('passed') else 'failed'}.",
                str(check.get("output", "")).splitlines()[-30:],
            )
        )
    return results


def _run_command(root: Path, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=root, text=True, capture_output=True, timeout=timeout, check=False)


def _git_status_check(root: Path) -> CheckResult:
    if not (root / ".git").exists():
        return CheckResult("git-status", "passed", "Production container has no Git metadata; repository files are available.")
    try:
        result = _run_command(root, ["git", "status", "--short"], 10)
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        return CheckResult("git-status", "warning", "Git status is unavailable.", [str(exc)])
    if result.returncode != 0:
        return CheckResult("git-status", "warning", "Unable to read repository status.", [(result.stderr or result.stdout).strip()])
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    unmerged = [line for line in lines if line.startswith(("UU", "AA", "DD", "AU", "UA", "DU", "UD"))]
    if unmerged:
        return CheckResult("git-status", "failed", f"{len(unmerged)} unmerged file(s) need resolution.", unmerged)
    if lines:
        return CheckResult("git-status", "warning", f"{len(lines)} changed file(s) in the workspace.", lines[:25])
    return CheckResult("git-status", "passed", "Workspace is clean.")


def _conflict_marker_check(root: Path) -> CheckResult:
    markers: list[str] = []
    for path in _iter_text_files(root):
        try:
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if line.startswith(("<<<<<<<", "=======", ">>>>>>>")):
                    markers.append(f"{path.relative_to(root)}:{number}: {line[:80]}")
                    break
        except OSError:
            continue
    if markers:
        return CheckResult("conflict-markers", "failed", f"{len(markers)} file(s) contain conflict markers.", markers)
    return CheckResult("conflict-markers", "passed", "No conflict markers found.")


def _python_compile_check(root: Path) -> CheckResult:
    files = [
        "amoscloud_ai/api/routes/agent.py",
        "amoscloud_ai/agentic_cloud_engine.py",
        "amoscloud_ai/autonomous_server.py",
        "amoscloud_ai/main.py",
        "amoscloud_ai/models.py",
        "amoscloud_ai/worker.py",
    ]
    existing = [str(root / item) for item in files if (root / item).exists()]
    result = _run_command(root, [sys.executable, "-m", "py_compile", *existing], 30)
    if result.returncode:
        return CheckResult("python-compile", "failed", "Python compile check failed.", (result.stderr or result.stdout).splitlines()[:30])
    return CheckResult("python-compile", "passed", f"Compiled {len(existing)} key module(s).")


def _server_tests_check(root: Path) -> CheckResult:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return CheckResult("server-tests", "warning", "Skipped nested pytest while endpoint tests are running.")
    executable = str(root / "venv" / "bin" / "python") if (root / "venv" / "bin" / "python").exists() else sys.executable
    result = _run_command(root, [executable, "-m", "pytest", "tests/test_server.py"], 90)
    output = (result.stdout + "\n" + result.stderr).splitlines()
    if result.returncode:
        return CheckResult("server-tests", "failed", "Focused server tests failed.", output[-30:])
    summary = next((line for line in reversed(output) if " passed" in line), "Focused server tests passed.")
    return CheckResult("server-tests", "passed", summary)


def _iter_text_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES:
            yield path
