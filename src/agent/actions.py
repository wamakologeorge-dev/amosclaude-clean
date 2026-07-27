"""Single Autonomous orchestrator for all Amosclaud entry points."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from amosclaud_os.agent.runtime_bridge import run_native_coding_if_requested
from src.amosclaud_security import (
    Capability,
    CommandState,
    Principal,
    SecurityError,
)
from src.amosclaud_security.command_bus import security_enforced
from src.amosclaud_security.runtime import authority_for_workspace
from src.foundation import AgentsPracticeStation, IntelligentFoundation
from src.services.code_analyzer import CodeAnalyzer
from src.services.file_manager import SafeFileManager
from src.services.runtime_exec import RuntimeExecutor

from .engineering_loop import AutonomousEngineeringLoop, LoopOutcome
from .model import AutonomousModelGateway
from .react_integration import AutonomousReactController
from .react_loop import ReactOutcome

_WRITE_MODES = frozenset({"build", "create", "deploy", "fix", "write"})
_MAX_BRAIN_LEVEL = 100
_MAX_ACADEMY_LEVEL = 5000


def _bounded_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, maximum))


def _resolve_learning_level(metadata: dict[str, Any]) -> int:
    """Map a simple 1-100 Codex profile onto the 1-5000 curriculum.

    The profile adjusts learning, evidence, and practice depth only. It never
    bypasses write authorization, protected branches, or human merge controls.
    """

    if "academy_level" in metadata:
        return _bounded_int(
            metadata["academy_level"],
            default=1,
            maximum=_MAX_ACADEMY_LEVEL,
        )
    configured = metadata.get(
        "codex_brain_level",
        os.getenv("AMOSCLAUD_CODEX_BRAIN_LEVEL", "100"),
    )
    brain_level = _bounded_int(
        configured,
        default=100,
        maximum=_MAX_BRAIN_LEVEL,
    )
    return min(_MAX_ACADEMY_LEVEL, brain_level * 50)


@dataclass
class AutonomousTask:
    objective: str
    mode: str = "plan"
    authorized_writes: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    fixer_grant: str | None = None
    security_repository: str | None = None
    security_target_sha: str | None = None
    security_parent_command_id: str | None = None


class AutonomousOrchestrator:
    """One coordinator for UI, API, webhooks, jobs, agents, and lessons."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.model = AutonomousModelGateway()
        self.analyzer = CodeAnalyzer(self.workspace)
        self.files = SafeFileManager(self.workspace)
        self.runtime = RuntimeExecutor(self.workspace)
        self.foundation = IntelligentFoundation(self.workspace)
        self.practice_station = AgentsPracticeStation(self.workspace)
        self.react = AutonomousReactController(self.workspace)
        self.engineering_loop = AutonomousEngineeringLoop(
            analyzer=self.analyzer,
            model=self.model,
            files=self.files,
            runtime=self.runtime,
            max_attempts=2,
        )

    def _fixer_write_authorized(
        self,
        task: AutonomousTask,
    ) -> tuple[bool, dict[str, Any]]:
        """Consume the Autonomous -> Fixer grant before any write-capable loop."""
        if task.mode not in _WRITE_MODES:
            return False, {"required": False, "verified": False}
        required = security_enforced()
        if not task.fixer_grant:
            if required:
                return False, {
                    "required": True,
                    "verified": False,
                    "reason": "fixer_grant_required",
                }
            return bool(task.authorized_writes), {
                "required": False,
                "verified": False,
                "legacy_authorization": bool(task.authorized_writes),
            }
        if not task.security_repository or not task.security_target_sha:
            return False, {
                "required": required,
                "verified": False,
                "reason": "security_target_missing",
            }
        authority = authority_for_workspace(self.workspace, required=True)
        assert authority is not None
        try:
            decision = authority.verify(
                task.fixer_grant,
                expected_subject=Principal.FIXER,
                repository=task.security_repository,
                target_sha=task.security_target_sha,
                objective=task.objective,
                required_capabilities=[Capability.REPAIR_APPLY],
                consume=True,
                expected_parent_command_id=task.security_parent_command_id,
            )
            grant = decision.grant
            assert grant is not None
            for state in (
                CommandState.RECEIVED,
                CommandState.AUTHORIZED,
                CommandState.PLANNED,
                CommandState.FIXER_AUTHORIZED,
            ):
                authority.transition(
                    command_id=grant.command_id,
                    correlation_id=grant.correlation_id,
                    state=state,
                    actor=Principal.FIXER,
                    detail={"mode": task.mode},
                )
            return True, {
                "required": required,
                "verified": True,
                "command_id": grant.command_id,
                "correlation_id": grant.correlation_id,
                "parent_command_id": grant.parent_command_id,
                "capabilities": list(grant.capabilities),
            }
        except SecurityError as exc:
            return False, {
                "required": required,
                "verified": False,
                "reason": type(exc).__name__,
            }

    def run_react(self, task: AutonomousTask) -> ReactOutcome:
        """Run Reason-Act-Observe-Verify beneath this same orchestrator."""
        guidance_modes = {"answer", "guide", "learn", "teach"}
        return self.react.run(
            task.objective,
            authorized_writes=False,
            execution_required=task.mode not in guidance_modes,
        )

    def run(self, task: AutonomousTask) -> LoopOutcome | ReactOutcome:
        if task.mode in {"react", "answer", "guide", "learn", "teach"}:
            return self.run_react(task)
        write_authorized, security = self._fixer_write_authorized(task)
        task.metadata["security"] = security
        level = _resolve_learning_level(task.metadata)
        founder_verified = bool(task.metadata.get("founder_verified", False))
        context = self.foundation.prepare(
            task.objective,
            authorized_writes=write_authorized,
            founder_verified=founder_verified,
            current_level=level,
        )
        outcome = self.engineering_loop.run(
            objective=task.objective,
            mode=task.mode,
            authorized_writes=(write_authorized and "write" in context.allowed_actions),
        )
        grant_command_id = security.get("command_id")
        correlation_id = security.get("correlation_id")
        if grant_command_id and correlation_id:
            authority = authority_for_workspace(self.workspace, required=True)
            assert authority is not None
            authority.transition(
                command_id=grant_command_id,
                correlation_id=correlation_id,
                state=CommandState.PATCH_PROPOSED,
                actor=Principal.FIXER,
                detail={"status": outcome.status},
            )
            authority.transition(
                command_id=grant_command_id,
                correlation_id=correlation_id,
                state=CommandState.VERIFYING,
                actor=Principal.VERIFIER,
                detail={"checks": len(outcome.checks)},
            )
            final_state = (
                CommandState.VERIFIED
                if outcome.status in {"success", "completed", "passed"}
                else CommandState.FAILED
            )
            authority.transition(
                command_id=grant_command_id,
                correlation_id=correlation_id,
                state=final_state,
                actor=Principal.VERIFIER,
                detail={"status": outcome.status},
            )
        practice = self.practice_station.practice(
            context.next_lesson["level"],
            verifier=lambda: outcome.checks
            or [
                {
                    "name": "engineering-loop",
                    "passed": outcome.status == "success",
                    "summary": "Engineering loop completed truthfully.",
                }
            ],
            evidence=[event.message for event in outcome.events],
        )
        security_result = (
            "verified and consumed." if write_authorized else "not authorized."
        )
        outcome.lessons.extend(
            [
                (
                    f"Foundation confidence: {context.confidence}; "
                    f"risk: {context.risk}."
                ),
                (
                    f"Practice Station: {practice.lesson}; score "
                    f"{practice.score}; status {practice.status}."
                ),
                f"Security chain: fixer grant {security_result}",
            ]
        )
        self.foundation.memory.remember(
            "project",
            (
                f"Objective: {task.objective}; outcome: {outcome.status}; "
                f"practice: {practice.status}"
            ),
            evidence=" | ".join(outcome.lessons),
        )
        return outcome


def _resolve_workspace(workspace: str) -> Path:
    """Resolve only server-managed application or repository workspaces.

    Calls coming from API routes should already be canonicalized to the
    configured workspace root. We still defensively re-validate that the final
    resolved path stays under one of the trusted roots, including after symlink
    resolution.
    """

    raw_workspace = str(workspace or ".").strip()
    if not raw_workspace or "\x00" in raw_workspace:
        raise HTTPException(status_code=400, detail="Invalid workspace path")

    base = Path(os.getenv("AMOSCLAUD_WORKSPACE_ROOT", ".")).expanduser().resolve()
    repository_root = Path(
        os.getenv("REPOSITORY_STORAGE_PATH", "data/repositories")
    ).expanduser().resolve()
    allowed_roots = tuple(dict.fromkeys((base, repository_root)))

    # Validate user-provided workspace text before constructing a filesystem path.
    if raw_workspace.startswith("~"):
        raise HTTPException(status_code=400, detail="Invalid workspace path")

    workspace_path = Path(raw_workspace)
    if not workspace_path.is_absolute() and ".." in workspace_path.parts:
        raise HTTPException(status_code=400, detail="Workspace escapes allowed root")

    if workspace_path.is_absolute():
        anchored: Path | None = None
        for root in allowed_roots:
            try:
                workspace_path.relative_to(root)
                anchored = workspace_path
                break
            except ValueError:
                continue
        if anchored is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Workspace must stay inside the application or repository "
                    "storage root"
                ),
            )
    else:
        anchored = base / workspace_path

    candidate = anchored.resolve()

    for root in allowed_roots:
        candidate = (root / workspace_path).resolve()
        try:
            candidate.relative_to(root)
            return candidate
        except ValueError:
            continue
    raise HTTPException(
        status_code=400,
        detail=(
            "Workspace must stay inside the application or repository storage root"
        ),
    )


def run_autonomous(
    objective: str,
    mode: str = "plan",
    authorized_writes: bool = False,
    workspace: str = ".",
    metadata: dict[str, Any] | None = None,
    fixer_grant: str | None = None,
    security_repository: str | None = None,
    security_target_sha: str | None = None,
    security_parent_command_id: str | None = None,
) -> dict[str, Any]:
    safe_workspace = _resolve_workspace(workspace)
    prepared = dict(metadata or {})
    task = AutonomousTask(
        objective=objective,
        mode=mode,
        authorized_writes=authorized_writes,
        metadata=prepared,
        fixer_grant=fixer_grant,
        security_repository=security_repository,
        security_target_sha=security_target_sha,
        security_parent_command_id=security_parent_command_id,
    )
    native = run_native_coding_if_requested(
        objective=objective,
        mode=mode,
        workspace=safe_workspace,
        authorized_writes=authorized_writes,
        metadata=prepared,
    )
    if native is not None:
        return native
    outcome = AutonomousOrchestrator(safe_workspace).run(task)
    return outcome.to_dict()
