"""Canonical Amosclaud Autonomous backend.

The product exposes exactly three concepts: Autonomous, Repository, and Results.
All model, repair, deployment, CI, document, and repository capabilities are
private abilities of this one Autonomous instance. No backend route or response
should present them as separate agents.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any

from src.agent.actions import AutonomousOrchestrator, AutonomousTask
from src.amosclaud_os.intelligence import AutonomousConnectorHub, ModelEngine
from src.amosclaud_security import (
    Capability,
    CommandState,
    Principal,
    SecurityError,
    bounded_repair_constraints,
)
from src.amosclaud_security.command_bus import security_enforced
from src.amosclaud_security.runtime import (
    authority_for_workspace,
    repository_identity,
    target_revision,
)


@dataclass(frozen=True)
class SystemIdentity:
    product: str = "Amosclaud"
    driver: str = "Amosclaud Autonomous"
    architecture: str = "one-autonomous-agent"
    authority: str = "founder-governed-signed-capability-chain"
    version: str = "5.0.0"


class AutonomousKernel:
    """The single Amosclaud Autonomous agent and backend composition root."""

    PRODUCT_AREAS = ("autonomous", "repository", "results")
    WRITE_MODES = frozenset({"build", "create", "deploy", "fix", "write"})

    def __init__(self, workspace: Path | str = ".") -> None:
        self.workspace = Path(workspace).resolve()
        self.identity = SystemIdentity()
        self._lock = RLock()
        self._orchestrator = AutonomousOrchestrator(self.workspace)
        self.model_engine = ModelEngine()
        self.connectors = AutonomousConnectorHub(self.workspace)
        self._started = monotonic()
        self._missions = 0

    @staticmethod
    def _required_root_capability(mode: str) -> Capability:
        if mode == "deploy":
            return Capability.DEPLOY_REQUEST
        return Capability.REPAIR_PLAN

    def _authorize_write_chain(
        self,
        *,
        objective: str,
        mode: str,
        repository: str,
        target_sha: str,
        security_grant: str | None,
        legacy_authorized_writes: bool,
    ) -> tuple[bool, str | None, dict[str, Any]]:
        """Verify Bot/Human -> Autonomous and issue Autonomous -> Fixer."""

        enforced = security_enforced()
        if not security_grant:
            if enforced:
                return False, None, {
                    "enforced": True,
                    "authorized": False,
                    "reason": "signed_security_grant_required",
                }
            return bool(legacy_authorized_writes), None, {
                "enforced": False,
                "authorized": bool(legacy_authorized_writes),
                "legacy_authorization": bool(legacy_authorized_writes),
            }

        authority = authority_for_workspace(self.workspace, required=True)
        assert authority is not None
        required = self._required_root_capability(mode)
        try:
            decision = authority.verify(
                security_grant,
                expected_subject=Principal.AUTONOMOUS,
                repository=repository,
                target_sha=target_sha,
                objective=objective,
                required_capabilities=[required],
                consume=True,
            )
            root = decision.grant
            assert root is not None
            authority.transition(
                command_id=root.command_id,
                correlation_id=root.correlation_id,
                state=CommandState.RECEIVED,
                actor=Principal.BOT,
                detail={"source": root.source},
            )
            authority.transition(
                command_id=root.command_id,
                correlation_id=root.correlation_id,
                state=CommandState.AUTHORIZED,
                actor=Principal.AUTONOMOUS,
                detail={"capabilities": list(root.capabilities)},
            )
            authority.transition(
                command_id=root.command_id,
                correlation_id=root.correlation_id,
                state=CommandState.PLANNED,
                actor=Principal.AUTONOMOUS,
                detail={"mode": mode},
            )

            if mode == "deploy":
                authority.transition(
                    command_id=root.command_id,
                    correlation_id=root.correlation_id,
                    state=CommandState.BLOCKED,
                    actor=Principal.AUTONOMOUS,
                    detail={
                        "reason": "deployment_execution_is_not_an_autonomous_capability"
                    },
                )
                return False, None, {
                    "enforced": True,
                    "authorized": False,
                    "command_id": root.command_id,
                    "correlation_id": root.correlation_id,
                    "reason": "deployment_execution_requires_separate_human_control",
                }

            constraints = bounded_repair_constraints(
                max_changed_files=min(
                    int(root.constraints.get("max_changed_files", 25)),
                    25,
                ),
                protected_prefixes=root.constraints.get("protected_prefixes", ()),
                protected_paths=root.constraints.get("protected_paths", ()),
                approval_profile=str(
                    root.constraints.get(
                        "approval_profile",
                        "human-command-bounded-repair",
                    )
                ),
            )
            fixer_grant = authority.issue(
                issuer=Principal.AUTONOMOUS,
                subject=Principal.FIXER,
                repository=repository,
                target_sha=target_sha,
                objective=objective,
                capabilities=[Capability.REPAIR_APPLY],
                constraints=constraints,
                source={
                    "kind": "autonomous-plan",
                    "id": root.command_id,
                    "root_source": root.source,
                },
                approval=root.approval,
                ttl_seconds=min(root.expires_at - root.issued_at, 900),
                correlation_id=root.correlation_id,
                parent_command_id=root.command_id,
            )
            return True, fixer_grant, {
                "enforced": True,
                "authorized": True,
                "command_id": root.command_id,
                "correlation_id": root.correlation_id,
                "issuer": root.issuer,
                "root_capabilities": list(root.capabilities),
                "fixer_capability": Capability.REPAIR_APPLY.value,
            }
        except SecurityError as exc:
            return False, None, {
                "enforced": enforced,
                "authorized": False,
                "reason": type(exc).__name__,
            }

    def execute(
        self,
        *,
        objective: str,
        mode: str = "plan",
        authorized_writes: bool = False,
        metadata: dict[str, Any] | None = None,
        security_grant: str | None = None,
    ) -> dict[str, Any]:
        """Run one governed task through the same Autonomous."""
        objective = objective.strip()
        mode = mode.strip().lower() or "plan"
        prepared = dict(metadata or {})
        if not objective:
            return self._stamp(
                {
                    "status": "failed",
                    "failed": True,
                    "error": "empty_objective",
                    "evidence": [],
                }
            )

        repository = repository_identity(
            self.workspace,
            str(prepared.get("repository") or "") or None,
        )
        target_sha = target_revision(self.workspace)
        fixer_grant: str | None = None
        security: dict[str, Any] = {
            "enforced": security_enforced(),
            "authorized": False,
            "repository": repository,
            "target_sha": target_sha,
        }
        effective_writes = False
        if mode in self.WRITE_MODES:
            effective_writes, fixer_grant, write_security = self._authorize_write_chain(
                objective=objective,
                mode=mode,
                repository=repository,
                target_sha=target_sha,
                security_grant=security_grant,
                legacy_authorized_writes=authorized_writes,
            )
            security.update(write_security)
            if not effective_writes:
                return self._stamp(
                    {
                        "status": "blocked",
                        "failed": False,
                        "error": str(
                            security.get("reason") or "write_not_authorized"
                        ),
                        "evidence": [
                            "The requested capability can make repository or deployment changes.",
                            "A valid, unexpired, one-time signed capability grant is required.",
                        ],
                        "security": security,
                    }
                )

        model_route = self.model_engine.route(objective)
        task = AutonomousTask(
            objective=objective,
            mode=mode,
            authorized_writes=effective_writes,
            metadata={
                "system": self.identity.product,
                "driver": self.identity.driver,
                "architecture": self.identity.architecture,
                "model_route": model_route,
                "security": security,
                **prepared,
            },
            fixer_grant=fixer_grant,
            security_repository=repository,
            security_target_sha=target_sha,
            security_parent_command_id=security.get("command_id"),
        )
        with self._lock:
            self._missions += 1
            outcome = self._orchestrator.run(task).to_dict()
        outcome["model_route"] = model_route
        outcome["available_capabilities"] = self.connectors.capabilities()
        outcome["security"] = {
            **security,
            "fixer_grant_issued": bool(fixer_grant),
            "grant_material_exposed": False,
        }
        return self._stamp(outcome)

    def run(
        self,
        *,
        objective: str,
        mode: str = "plan",
        authorized_writes: bool = False,
        repository: str | None = None,
        metadata: dict[str, Any] | None = None,
        security_grant: str | None = None,
    ) -> dict[str, Any]:
        """Return the public Autonomous, Repository, and Results contract."""
        raw = self.execute(
            objective=objective,
            mode=mode,
            authorized_writes=authorized_writes,
            security_grant=security_grant,
            metadata={"repository": repository, **dict(metadata or {})},
        )
        status = self._result_status(raw)
        security = dict(raw.get("security") or {})
        return {
            "autonomous": {
                "name": self.identity.driver,
                "identity": "one-agent",
                "mission_number": raw.get("mission_number"),
                "capability": mode,
            },
            "repository": {
                "name": repository,
                "workspace": str(self.workspace),
                "writes_authorized": bool(security.get("authorized")),
            },
            "results": {
                "status": status,
                "failed": status == "failed",
                "blocked": status == "blocked",
                "error": raw.get("error"),
                "evidence": list(raw.get("evidence") or []),
                "artifacts": list(raw.get("artifacts") or []),
                "logs": list(raw.get("logs") or []),
                "tests": raw.get("tests"),
                "deployment": raw.get("deployment"),
                "source": raw.get("source"),
                "security": security,
            },
        }

    @staticmethod
    def _result_status(raw: dict[str, Any]) -> str:
        """Normalize runtime output without turning plans or blockers into success."""
        status = str(raw.get("status") or "").strip().lower()
        if raw.get("failed") is True or status in {"error", "failed"}:
            return "failed"
        if raw.get("error") or status in {"blocked", "denied", "waiting"}:
            return "blocked"
        if status in {"completed", "deployed", "passed", "success", "succeeded"}:
            return "completed"
        if status in {"planned", "planning", "ready"}:
            return "planned"
        if status in {"running", "verifying"}:
            return status
        return "completed" if raw.get("evidence") else "planned"

    def model_respond(
        self,
        *,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Use model inference as an internal ability of Autonomous."""
        with self._lock:
            result = self.model_engine.respond(prompt, context=context).to_dict()
        return self._stamp(result)

    def read_document(self, relative_path: str) -> dict[str, Any]:
        """Read a repository document through the same Autonomous."""
        with self._lock:
            result = self.connectors.read_document(relative_path)
        return self._stamp(result)

    def write_document(
        self,
        relative_path: str,
        content: str,
        *,
        authorized_writes: bool = False,
        security_grant: str | None = None,
        repository: str | None = None,
    ) -> dict[str, Any]:
        """Write a repository document only through the signed repair chain."""
        objective = f"write repository document {relative_path}"
        repository_name = repository_identity(self.workspace, repository)
        target_sha = target_revision(self.workspace)
        authorized, fixer_grant, security = self._authorize_write_chain(
            objective=objective,
            mode="write",
            repository=repository_name,
            target_sha=target_sha,
            security_grant=security_grant,
            legacy_authorized_writes=authorized_writes,
        )
        if not authorized:
            return self._stamp(
                {
                    "status": "blocked",
                    "error": security.get("reason") or "write_not_authorized",
                    "security": security,
                }
            )
        if fixer_grant:
            authority = authority_for_workspace(self.workspace, required=True)
            assert authority is not None
            decision = authority.verify(
                fixer_grant,
                expected_subject=Principal.FIXER,
                repository=repository_name,
                target_sha=target_sha,
                objective=objective,
                required_capabilities=[Capability.REPAIR_APPLY],
                consume=True,
                expected_parent_command_id=security.get("command_id"),
            )
            security["fixer_command_id"] = decision.command_id
        with self._lock:
            result = self.connectors.write_document(
                relative_path,
                content,
                authorized=True,
            )
        result["security"] = security
        return self._stamp(result)

    def assist(
        self,
        *,
        message: str,
        evidence: list[str] | None = None,
        result_locations: list[str] | None = None,
        execute: bool = False,
        authorized_writes: bool = False,
        security_grant: str | None = None,
    ) -> dict[str, Any]:
        """Continue the same Autonomous conversation; never create another identity."""
        from src.agent.cloud_agent import chat_with_autonomous

        if execute and authorized_writes and security_enforced() and not security_grant:
            return self._stamp(
                {
                    "status": "blocked",
                    "error": "signed_security_grant_required",
                    "evidence": [
                        "Conversational execution cannot bypass the command security chain."
                    ],
                }
            )
        with self._lock:
            result = chat_with_autonomous(
                message,
                evidence or [],
                result_locations or [],
                execute=execute,
                authorized_writes=(authorized_writes and not security_enforced()),
                workspace=str(self.workspace),
            )
        return self._stamp(result)

    def repair(
        self,
        *,
        issue: str,
        authorized_writes: bool = False,
        security_grant: str | None = None,
        repository: str | None = None,
    ) -> dict[str, Any]:
        """Compatibility entry point for the same Autonomous fixing a problem."""
        return self.execute(
            objective=issue,
            mode="fix",
            authorized_writes=authorized_writes,
            security_grant=security_grant,
            metadata={
                "requested_capability": "repair",
                "repository": repository,
            },
        )

    def _stamp(self, result: dict[str, Any]) -> dict[str, Any]:
        stamped = dict(result)
        stamped["agent"] = self.identity.driver
        stamped["agent_identity"] = "one-agent"
        stamped["system_identity"] = asdict(self.identity)
        stamped["mission_number"] = self._missions
        stamped["workspace"] = str(self.workspace)
        stamped["source"] = "src.amosclaud_os.kernel.AutonomousKernel"
        return stamped

    def status(self) -> dict[str, Any]:
        return {
            **asdict(self.identity),
            "status": "ready",
            "workspace": str(self.workspace),
            "missions_started": self._missions,
            "uptime_seconds": round(monotonic() - self._started, 3),
            "single_source": "src.amosclaud_os.kernel.AutonomousKernel",
            "model": self.model_engine.configuration(),
            "capabilities": self.connectors.capabilities(),
            "jobs": self.connectors.jobs(),
            "product_areas": list(self.PRODUCT_AREAS),
            "public_agents": [self.identity.driver],
            "write_modes": sorted(self.WRITE_MODES),
            "security": {
                "enforced": security_enforced(),
                "chain": [
                    Principal.BOT.value,
                    Principal.AUTONOMOUS.value,
                    Principal.FIXER.value,
                    Principal.VERIFIER.value,
                    Principal.PUBLISHER.value,
                ],
                "direct_default_branch_writes": False,
                "secret_reads": False,
                "autonomous_deployment_execution": False,
            },
        }


_KERNELS: dict[str, AutonomousKernel] = {}
_KERNELS_LOCK = RLock()


def get_autonomous_kernel(workspace: Path | str = ".") -> AutonomousKernel:
    """Return one process-wide Autonomous instance per resolved workspace."""
    key = str(Path(workspace).resolve())
    with _KERNELS_LOCK:
        kernel = _KERNELS.get(key)
        if kernel is None:
            kernel = AutonomousKernel(key)
            _KERNELS[key] = kernel
        return kernel
