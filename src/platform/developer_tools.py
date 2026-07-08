"""
DeveloperTools — Linting, formatting, testing, and debugging utilities.

Provides a unified interface to common developer tools so that Amosclaud-AI
can trigger quality checks as part of an automated workflow or on-demand
through the platform CLI / API.
"""

import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ToolStatus(Enum):
    """Result status for a developer-tool run."""
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class ToolResult:
    """Outcome of running a single developer tool."""
    tool: str
    status: ToolStatus
    output: str
    duration_seconds: float
    issues: List[str] = field(default_factory=list)
    ran_at: datetime = field(default_factory=datetime.now)

    @property
    def passed(self) -> bool:
        return self.status == ToolStatus.PASSED


@dataclass
class QualityReport:
    """Aggregated report for a full quality check run."""
    target: str
    results: List[ToolResult]
    started_at: datetime = field(default_factory=datetime.now)

    @property
    def overall_passed(self) -> bool:
        return all(r.status in (ToolStatus.PASSED, ToolStatus.SKIPPED) for r in self.results)

    def summary(self) -> Dict[str, Any]:
        return {
            "target": self.target,
            "overall_passed": self.overall_passed,
            "tools_run": len(self.results),
            "passed": sum(1 for r in self.results if r.status == ToolStatus.PASSED),
            "failed": sum(1 for r in self.results if r.status == ToolStatus.FAILED),
            "skipped": sum(1 for r in self.results if r.status == ToolStatus.SKIPPED),
            "started_at": self.started_at.isoformat(),
        }


class DeveloperTools:
    """
    Unified developer-tooling interface for the Amosclaud Platform.

    The class auto-detects which tools are installed and skips gracefully
    when a tool is not available, so the platform works in minimal
    environments too.

    Usage::

        tools = DeveloperTools(project_root="/path/to/project")
        report = tools.run_quality_check()
        print(report.summary())
    """

    # Mapping from a tool name to the shell command used to invoke it.
    _LINTERS: Dict[str, str] = {
        "flake8": "flake8 {target} --max-line-length=120 --statistics",
        "pylint": "pylint {target} --output-format=text",
        "mypy": "mypy {target} --ignore-missing-imports",
        "bandit": "bandit -r {target} -ll",
    }

    _FORMATTERS: Dict[str, str] = {
        "black": "black {target} --check --diff",
        "isort": "isort {target} --check-only --diff",
    }

    _TEST_RUNNERS: Dict[str, str] = {
        "pytest": "pytest {target} -v --tb=short",
    }

    def __init__(
        self,
        project_root: str = ".",
        timeout: int = 300,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.timeout = timeout
        self._run_history: List[QualityReport] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_quality_check(
        self,
        target: Optional[str] = None,
        linters: bool = True,
        formatters: bool = True,
        tests: bool = True,
    ) -> QualityReport:
        """
        Run linting, formatting checks, and tests against *target*.

        *target* defaults to the project root.
        """
        resolved_target = str(target or self.project_root)
        logger.info("Running quality check on '%s'", resolved_target)

        results: List[ToolResult] = []

        if linters:
            results.extend(self._run_tool_group(self._LINTERS, resolved_target))
        if formatters:
            results.extend(self._run_tool_group(self._FORMATTERS, resolved_target))
        if tests:
            tests_dir = str(self.project_root / "tests")
            results.extend(self._run_tool_group(self._TEST_RUNNERS, tests_dir))

        report = QualityReport(target=resolved_target, results=results)
        self._run_history.append(report)

        status = "PASSED" if report.overall_passed else "FAILED"
        logger.info("Quality check %s — %d tool(s) run", status, len(results))
        return report

    def lint(self, target: Optional[str] = None) -> List[ToolResult]:
        """Run all available linters on *target*."""
        resolved_target = str(target or self.project_root)
        return self._run_tool_group(self._LINTERS, resolved_target)

    def format_code(
        self, target: Optional[str] = None, apply: bool = False
    ) -> List[ToolResult]:
        """
        Check (or apply) code formatting.

        When *apply=True* the formatters are invoked without ``--check``
        so that they reformat files in-place.
        """
        resolved_target = str(target or self.project_root)
        if apply:
            formatters = {
                "black": "black {target}",
                "isort": "isort {target}",
            }
        else:
            formatters = self._FORMATTERS
        return self._run_tool_group(formatters, resolved_target)

    def run_tests(
        self,
        target: Optional[str] = None,
        extra_args: str = "",
    ) -> List[ToolResult]:
        """Run the test suite using pytest."""
        tests_dir = str(target or self.project_root / "tests")
        runners = {
            "pytest": f"pytest {{target}} -v --tb=short {extra_args}".strip()
        }
        return self._run_tool_group(runners, tests_dir)

    def check_security(self, target: Optional[str] = None) -> List[ToolResult]:
        """Run bandit security scan."""
        resolved_target = str(target or self.project_root)
        return self._run_tool_group(
            {"bandit": "bandit -r {target} -ll"}, resolved_target
        )

    def get_history(self) -> List[QualityReport]:
        """Return all quality-check reports produced in this session."""
        return list(self._run_history)

    def is_tool_available(self, tool_name: str) -> bool:
        """Return True if *tool_name* is importable / on the PATH."""
        result = subprocess.run(
            f"{tool_name} --version",
            shell=True,
            capture_output=True,
        )
        return result.returncode == 0

    def list_available_tools(self) -> Dict[str, bool]:
        """Return a mapping of tool name → availability."""
        all_tools = (
            list(self._LINTERS.keys())
            + list(self._FORMATTERS.keys())
            + list(self._TEST_RUNNERS.keys())
        )
        return {tool: self.is_tool_available(tool) for tool in all_tools}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_tool_group(
        self, tool_map: Dict[str, str], target: str
    ) -> List[ToolResult]:
        results: List[ToolResult] = []
        for tool_name, cmd_template in tool_map.items():
            results.append(self._run_single_tool(tool_name, cmd_template, target))
        return results

    def _run_single_tool(
        self, tool_name: str, cmd_template: str, target: str
    ) -> ToolResult:
        if not self.is_tool_available(tool_name):
            logger.debug("Skipping '%s' — not installed", tool_name)
            return ToolResult(
                tool=tool_name,
                status=ToolStatus.SKIPPED,
                output="",
                duration_seconds=0.0,
            )

        cmd = cmd_template.format(target=target)
        logger.info("Running: %s", cmd)
        start = datetime.now()
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(self.project_root),
            )
            duration = (datetime.now() - start).total_seconds()
            output = (proc.stdout + proc.stderr).strip()
            issues = [line for line in output.splitlines() if line.strip()]
            status = ToolStatus.PASSED if proc.returncode == 0 else ToolStatus.FAILED
            if status == ToolStatus.FAILED:
                logger.warning("'%s' reported issues", tool_name)
            return ToolResult(
                tool=tool_name,
                status=status,
                output=output,
                duration_seconds=duration,
                issues=issues,
            )
        except subprocess.TimeoutExpired:
            logger.error("'%s' timed out after %ds", tool_name, self.timeout)
            return ToolResult(
                tool=tool_name,
                status=ToolStatus.ERROR,
                output=f"Timed out after {self.timeout}s",
                duration_seconds=float(self.timeout),
            )
        except Exception as exc:
            logger.error("'%s' raised an exception: %s", tool_name, exc)
            return ToolResult(
                tool=tool_name,
                status=ToolStatus.ERROR,
                output=str(exc),
                duration_seconds=0.0,
            )
