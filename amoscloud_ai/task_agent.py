"""Plan-first task controller for Amosclaud autonomous engineering work.

This module gives the autonomous runtime a clear agent lifecycle:
receive the task, form a bounded plan, execute inside the selected workspace,
verify the result, and report evidence. The deterministic runtime remains the
fallback when the model provider is unavailable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from amoscloud_ai.engineering_agent import EngineeringAgentError, EngineeringRun, run_engineering_agent


@dataclass
class TaskStep:
    number: int
    title: str
    status: str = "pending"
    detail: str = ""


@dataclass
class TaskAgentRun:
    run_id: str
    objective: str
    status: str
    summary: str
    applied: bool
    plan: list[TaskStep] = field(default_factory=list)
    changes: list[dict[str, Any]] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)


def _base_plan(apply_changes: bool) -> list[TaskStep]:
    return [
        TaskStep(1, "Receive and understand the task"),
        TaskStep(2, "Inspect repository context and recall relevant memory"),
        TaskStep(3, "Prepare a safe, minimal implementation plan"),
        TaskStep(4, "Execute approved file changes" if apply_changes else "Prepare changes without writing files"),
        TaskStep(5, "Compile and test the result"),
        TaskStep(6, "Report outcome, evidence, and remaining risks"),
    ]


def _mark(plan: list[TaskStep], number: int, status: str, detail: str = "") -> None:
    for step in plan:
        if step.number == number:
            step.status = status
            step.detail = detail
            return


def _step_log(step: TaskStep) -> str:
    suffix = f" — {step.detail}" if step.detail else ""
    return f"Plan step {step.number}: {step.title} [{step.status}]{suffix}"


def run_task_agent(
    repository_root: Path,
    objective: str,
    *,
    workspace_path: str | None = None,
    apply_changes: bool = True,
) -> TaskAgentRun:
    """Receive, plan, execute, verify, and report one engineering task."""
    run_id = uuid.uuid4().hex
    objective = objective.strip()
    if not objective:
        raise EngineeringAgentError("A task objective is required")

    plan = _base_plan(apply_changes)
    logs = [
        f"Task {run_id}: received",
        f"Objective: {objective}",
        f"Mode: {'execute' if apply_changes else 'plan-only'}",
    ]
    _mark(plan, 1, "completed", "Task accepted and bounded to the Amosclaud workspace.")
    _mark(plan, 2, "running", "Inspecting supported source files and agent memory.")
    logs.extend(_step_log(step) for step in plan[:2])

    try:
        engineering: EngineeringRun = run_engineering_agent(
            repository_root,
            objective,
            workspace_path=workspace_path,
            apply_changes=apply_changes,
        )
    except EngineeringAgentError as exc:
        _mark(plan, 2, "failed", str(exc))
        for number in range(3, 7):
            _mark(plan, number, "blocked", "Stopped safely before further work.")
        logs.extend(_step_log(step) for step in plan[1:])
        return TaskAgentRun(
            run_id=run_id,
            objective=objective,
            status="blocked",
            summary="The task agent stopped safely before completing the task.",
            applied=False,
            plan=plan,
            evidence=[f"EngineeringAgentError: {exc}"],
            logs=logs,
        )
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        _mark(plan, 2, "failed", detail)
        for number in range(3, 7):
            _mark(plan, number, "blocked", "Stopped safely before further work.")
        logs.extend(_step_log(step) for step in plan[1:])
        return TaskAgentRun(
            run_id=run_id,
            objective=objective,
            status="failed",
            summary="The task agent failed safely while preparing the task.",
            applied=False,
            plan=plan,
            evidence=[detail],
            logs=logs,
        )

    _mark(plan, 2, "completed", "Repository context and relevant memory were inspected.")
    _mark(plan, 3, "completed", engineering.summary)
    if apply_changes:
        _mark(plan, 4, "completed" if engineering.applied else "failed", f"{len(engineering.changes)} file change(s) processed.")
    else:
        _mark(plan, 4, "completed", f"{len(engineering.changes)} change(s) planned; no files written.")

    failed_checks = [check for check in engineering.checks if not check.get("passed", False)]
    if engineering.checks:
        _mark(plan, 5, "failed" if failed_checks else "completed", f"{len(engineering.checks) - len(failed_checks)} passed; {len(failed_checks)} failed.")
    else:
        _mark(plan, 5, "completed", "No applicable verification command was required.")

    final_status = "failed" if failed_checks else "completed"
    _mark(plan, 6, "completed", "Outcome and evidence prepared.")

    changes = [
        {"path": change.path, "status": change.status, "bytes_written": change.bytes_written}
        for change in engineering.changes
    ]
    evidence = [f"Engineering run: {engineering.run_id}", f"Workspace: {engineering.workspace}", *engineering.evidence]
    logs.extend(_step_log(step) for step in plan[1:])
    logs.extend(f"Change: {item['status']} {item['path']}" for item in changes)
    logs.extend(
        f"Check: {check.get('name', 'verification')} — {'passed' if check.get('passed') else 'failed'}"
        for check in engineering.checks
    )

    return TaskAgentRun(
        run_id=run_id,
        objective=objective,
        status=final_status,
        summary=engineering.summary,
        applied=engineering.applied,
        plan=plan,
        changes=changes,
        checks=engineering.checks,
        evidence=evidence,
        logs=logs,
    )
