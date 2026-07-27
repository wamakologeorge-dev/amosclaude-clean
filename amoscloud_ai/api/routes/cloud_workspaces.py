"""Authenticated control-plane routes for isolated Amosclaud workspaces."""

from __future__ import annotations

import re
import sqlite3
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from amoscloud_ai import workspace_runtime, workspace_terminal
from amoscloud_ai.api.routes.repositories import (
    _access,
    _current_user,
    _db,
    _require_owner,
    _require_write,
)

router = APIRouter(prefix="/cloud-workspaces", tags=["cloud-workspaces"])


class TerminalTicketV2Request(BaseModel):
    terminal_id: str = Field(pattern=r"^term_[a-z0-9]{8,32}$")
    profile: str = Field(default="bash", pattern=r"^(bash|sh|python)$")


class TerminalAgentMessage(BaseModel):
    agent: Literal["doctor", "fixer", "autonomous", "underground"]
    message: str = Field(min_length=1, max_length=12000)
    branch: str = Field(default="main", min_length=1, max_length=255)
    terminal_id: str | None = Field(
        default=None,
        pattern=r"^term_[a-z0-9]{8,32}$",
    )
    profile: Literal["bash", "sh", "python"] = "bash"
    allow_changes: bool = False
    terminal_output: str = Field(default="", max_length=12000)


_TERMINAL_AGENTS: dict[str, dict[str, Any]] = {
    "doctor": {
        "name": "Amosclaud Doctor",
        "description": (
            "Diagnoses repository, command, dependency, build, test, and environment "
            "failures without changing files."
        ),
        "write_capable": False,
        "quick_prompts": [
            "Diagnose the last terminal failure and identify the root cause.",
            "Inspect this repository and list the highest-risk engineering problems.",
            "Explain which verification command should run next and why.",
        ],
    },
    "fixer": {
        "name": "Amosclaud Fixer",
        "description": (
            "Prepares a bounded repair, changes files only when explicitly authorized, "
            "and requires verification evidence."
        ),
        "write_capable": True,
        "quick_prompts": [
            "Repair the failure shown in the terminal and run the relevant checks.",
            "Fix the current build or test regression with the smallest safe change.",
            "Review the working tree and repair only verified defects.",
        ],
    },
    "autonomous": {
        "name": "Amosclaud Autonomous Agent",
        "description": (
            "Plans and performs an end-to-end engineering task in the selected repository, "
            "then reports exact checks, changes, or blockers."
        ),
        "write_capable": True,
        "quick_prompts": [
            "Complete the next useful engineering task and verify the result.",
            "Build the requested feature in this repository with tests.",
            "Inspect, plan, implement, and verify the safest solution.",
        ],
    },
    "underground": {
        "name": "Amosclaud Underground Fixer",
        "description": (
            "Safe escalation for stubborn failures after normal diagnosis and repair. "
            "It cannot force-push, bypass checks, or write to protected branches."
        ),
        "write_capable": True,
        "quick_prompts": [
            "Escalate this unresolved failure and find the deeper architectural cause.",
            "Attempt a bounded deep repair after the normal fixer failed.",
            "Analyze the repeated failure pattern and propose or apply a verified recovery.",
        ],
    },
}

_ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_SECRET_ASSIGNMENT = re.compile(
    r"(?im)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY)[A-Z0-9_]*)"
    r"\s*[:=]\s*([^\s]+)"
)
_SECRET_VALUE = re.compile(
    r"(?i)\b(?:bearer\s+)[A-Za-z0-9._~+/=-]{12,}|"
    r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,})|"
    r"\b(?:sk-[A-Za-z0-9_-]{20,})"
)


def _repository(repository_id: int, user_id: int) -> sqlite3.Row:
    with _db() as db:
        return _access(db, repository_id, user_id)


def _workspace(repository_id: int, user: sqlite3.Row) -> dict:
    repository = _repository(repository_id, int(user["id"]))
    _require_write(repository)
    return workspace_runtime.workspace_for_repository(
        int(repository["id"]), int(repository["owner_id"])
    )


def _running_workspace(repository_id: int, user: sqlite3.Row) -> dict:
    workspace = _workspace(repository_id, user)
    if not workspace_runtime.configured():
        raise HTTPException(status_code=503, detail="Workspace runtime is not configured")
    try:
        container = workspace_runtime.remote_status(workspace)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Workspace runtime is currently unavailable.",
        ) from exc
    if not container.get("running"):
        raise HTTPException(status_code=409, detail="Start the workspace first")
    return workspace


def _safe_terminal_output(value: str) -> str:
    """Clip and redact likely credentials before terminal output reaches an agent."""

    cleaned = _ANSI_ESCAPE.sub("", str(value or "")).replace("\x00", "")
    cleaned = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[redacted]", cleaned)
    cleaned = _SECRET_VALUE.sub("[redacted]", cleaned)
    return cleaned[-6000:]


def _agent_objective(
    *,
    repository_id: int,
    body: TerminalAgentMessage,
    spec: dict[str, Any],
    terminal_output: str,
) -> str:
    lines = [
        f"Act as {spec['name']} inside the Amosclaud terminal support hub.",
        f"Selected native repository ID: {repository_id}.",
        f"Selected branch: {body.branch}.",
        (
            "Return only truthful actions, exact evidence, and explicit blockers. "
            "Never claim a file changed or a check passed unless the runtime confirms it."
        ),
    ]
    if body.agent == "doctor":
        lines.append("Diagnosis only: do not modify repository files.")
    elif not body.allow_changes:
        lines.append("Planning mode: changes are not authorized for this message.")
    elif body.agent == "underground":
        lines.append(
            "Escalation mode is bounded: no force push, no protected-branch write, "
            "no bypass of checks, and verification is mandatory."
        )
    else:
        lines.append("Verified repository changes are authorized for this message.")
    lines.extend(["", "User request:", body.message.strip()])
    if terminal_output:
        lines.extend(
            [
                "",
                "User-approved recent terminal output (likely secrets were redacted):",
                "--- terminal output ---",
                terminal_output,
                "--- end terminal output ---",
            ]
        )
    return "\n".join(lines)


@router.get("/runtime")
def runtime_status(user: sqlite3.Row = Depends(_current_user)) -> dict:
    del user
    return workspace_runtime.runtime_health()


@router.get("/repositories/{repository_id}")
def repository_workspace_status(
    repository_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    workspace = _workspace(repository_id, user)
    payload = {
        "workspace": workspace,
        "runtime": workspace_runtime.runtime_health(),
        "persistent_repository": True,
    }
    if workspace_runtime.configured() and workspace["runtime_status"] != "not_started":
        try:
            payload["container"] = workspace_runtime.remote_status(workspace)
        except RuntimeError:
            payload["container_error"] = "Unable to retrieve container status."
    return payload


@router.post("/repositories/{repository_id}/start")
def start_repository_workspace(
    repository_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    workspace = _workspace(repository_id, user)
    if not workspace_runtime.configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "The isolated workspace runtime is not configured. Set "
                "AMOSCLAUD_WORKSPACE_RUNTIME_URL and AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN."
            ),
        )
    try:
        container = workspace_runtime.start_workspace(
            workspace,
            environment={
                "AMOSCLAUD_PROJECT_REPOSITORY_ID": str(repository_id),
                "AMOSCLAUD_PROJECT_OWNER_ID": str(workspace["owner_id"]),
            },
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Workspace runtime is currently unavailable.",
        ) from exc
    return {"workspace": workspace, "container": container}


@router.post("/repositories/{repository_id}/stop")
def stop_repository_workspace(
    repository_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    workspace = _workspace(repository_id, user)
    try:
        container = workspace_runtime.stop_workspace(workspace)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Workspace runtime is currently unavailable.",
        ) from exc
    return {"workspace": workspace, "container": container}


@router.post("/repositories/{repository_id}/terminal-ticket")
def create_terminal_ticket(
    repository_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    workspace = _running_workspace(repository_id, user)
    try:
        return workspace_runtime.terminal_ticket(workspace, int(user["id"]))
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Workspace runtime is currently unavailable.",
        ) from exc


@router.post("/repositories/{repository_id}/terminal-ticket-v2")
def create_terminal_ticket_v2(
    repository_id: int,
    body: TerminalTicketV2Request,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    """Create a session-bound ticket for the complete browser terminal."""

    workspace = _running_workspace(repository_id, user)
    try:
        return workspace_terminal.terminal_ticket(
            workspace,
            int(user["id"]),
            terminal_id=body.terminal_id,
            profile=body.profile,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Workspace terminal is currently unavailable.",
        ) from exc


@router.get("/repositories/{repository_id}/agent-hub")
def terminal_agent_hub(
    repository_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    """Describe the terminal-side engineering agents and their safety contract."""

    repository = _repository(repository_id, int(user["id"]))
    _require_write(repository)
    return {
        "repository_id": repository_id,
        "agents": [
            {"id": agent_id, **spec}
            for agent_id, spec in _TERMINAL_AGENTS.items()
        ],
        "policy": {
            "changes_require_explicit_authorization": True,
            "verification_required": True,
            "terminal_output_shared_only_when_selected": True,
            "force_push_allowed": False,
            "protected_branch_bypass_allowed": False,
            "success_requires_runtime_evidence": True,
        },
    }


@router.post("/repositories/{repository_id}/agent-hub/messages")
def terminal_agent_message(
    repository_id: int,
    body: TerminalAgentMessage,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    """Run one truthful agent-hub turn against the selected native repository."""

    repository = _repository(repository_id, int(user["id"]))
    _require_write(repository)
    spec = _TERMINAL_AGENTS[body.agent]
    changes_authorized = bool(body.allow_changes and spec["write_capable"])
    terminal_output = _safe_terminal_output(body.terminal_output)

    if body.agent == "doctor":
        mode = "inspect"
    elif body.agent in {"fixer", "underground"} and changes_authorized:
        mode = "fix"
    elif body.agent == "autonomous" and changes_authorized:
        mode = "build"
    else:
        mode = "inspect"

    objective = _agent_objective(
        repository_id=repository_id,
        body=body,
        spec=spec,
        terminal_output=terminal_output,
    )
    metadata = {
        "repository_id": repository_id,
        "branch": body.branch,
        "source": "workspace-terminal-agent-hub",
        "terminal_agent": body.agent,
        "terminal_id": body.terminal_id,
        "terminal_profile": body.profile,
        "terminal_context_attached": bool(terminal_output),
        "execution_contract": "native-or-truthful-blocker",
        "use_agent": True,
        "apply_changes": changes_authorized,
        "run_doctor": True,
        "run_tests": changes_authorized and body.agent != "doctor",
        "run_fixer": changes_authorized and body.agent in {"fixer", "underground"},
        "require_verification": True,
        "return_evidence": True,
        "allow_force_push": False,
        "allow_protected_branch_write": False,
        "underground_safe_mode": body.agent == "underground",
    }

    from amosclaud_os.agent.executor import execute_native_operation

    result = execute_native_operation(
        user=user,
        objective=objective,
        mode=mode,
        metadata=metadata,
    )
    if result is None:
        raise HTTPException(
            status_code=422,
            detail="The selected agent did not receive an engineering objective.",
        )
    return {
        "message_id": str(uuid.uuid4()),
        "agent": body.agent,
        "agent_name": spec["name"],
        "status": "completed" if result.succeeded else "blocked",
        "reply": result.summary,
        "operation": result.operation,
        "changes_authorized": changes_authorized,
        "terminal_context_used": bool(terminal_output),
        "evidence": result.evidence,
        "logs": result.logs,
        "resource": result.resource,
    }


@router.delete("/repositories/{repository_id}", status_code=204)
def delete_repository_workspace(
    repository_id: int,
    response: Response,
    user: sqlite3.Row = Depends(_current_user),
) -> Response:
    repository = _repository(repository_id, int(user["id"]))
    _require_owner(repository)
    workspace = workspace_runtime.workspace_for_repository(
        int(repository["id"]), int(repository["owner_id"])
    )
    if workspace_runtime.configured():
        try:
            workspace_runtime.delete_workspace(workspace)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail="Workspace runtime is currently unavailable.",
            ) from exc
    with _db() as db:
        db.execute("DELETE FROM cloud_workspaces WHERE id=?", (workspace["id"],))
        db.commit()
    response.status_code = 204
    return response
