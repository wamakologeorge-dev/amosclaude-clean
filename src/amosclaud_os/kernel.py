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


@dataclass(frozen=True)
class SystemIdentity:
    product: str = "Amosclaud"
    driver: str = "Amosclaud Autonomous"
    architecture: str = "one-autonomous-agent"
    authority: str = "founder-governed"
    version: str = "4.1.0"


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

    def execute(
        self,
        *,
        objective: str,
        mode: str = "plan",
        authorized_writes: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run one governed task through the same Autonomous."""
        objective = objective.strip()
        mode = mode.strip().lower() or "plan"
        if not objective:
            return self._stamp(
                {
                    "status": "failed",
                    "failed": True,
                    "error": "empty_objective",
                    "evidence": [],
                }
            )
        if mode in self.WRITE_MODES and not authorized_writes:
            return self._stamp(
                {
                    "status": "blocked",
                    "failed": False,
                    "error": "write_not_authorized",
                    "evidence": [
                        "The requested capability can make repository or deployment changes.",
                        "Explicit write authorization is required before execution.",
                    ],
                }
            )

        model_route = self.model_engine.route(objective)
        task = AutonomousTask(
            objective=objective,
            mode=mode,
            authorized_writes=authorized_writes,
            metadata={
                "system": self.identity.product,
                "driver": self.identity.driver,
                "architecture": self.identity.architecture,
                "model_route": model_route,
                **dict(metadata or {}),
            },
        )
        with self._lock:
            self._missions += 1
            outcome = self._orchestrator.run(task).to_dict()
        outcome["model_route"] = model_route
        outcome["available_capabilities"] = self.connectors.capabilities()
        return self._stamp(outcome)

    def run(
        self,
        *,
        objective: str,
        mode: str = "plan",
        authorized_writes: bool = False,
        repository: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the public Autonomous, Repository, and Results contract."""
        raw = self.execute(
            objective=objective,
            mode=mode,
            authorized_writes=authorized_writes,
            metadata={"repository": repository, **dict(metadata or {})},
        )
        status = self._result_status(raw)
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
                "writes_authorized": authorized_writes,
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
    ) -> dict[str, Any]:
        """Write a repository document only after explicit authorization."""
        with self._lock:
            result = self.connectors.write_document(
                relative_path,
                content,
                authorized=authorized_writes,
            )
        return self._stamp(result)

    def assist(
        self,
        *,
        message: str,
        evidence: list[str] | None = None,
        result_locations: list[str] | None = None,
        execute: bool = False,
        authorized_writes: bool = False,
    ) -> dict[str, Any]:
        """Continue the same Autonomous conversation; never create another identity."""
        from src.agent.cloud_agent import chat_with_autonomous

        with self._lock:
            result = chat_with_autonomous(
                message,
                evidence or [],
                result_locations or [],
                execute=execute,
                authorized_writes=authorized_writes,
                workspace=str(self.workspace),
            )
        return self._stamp(result)

    def repair(self, *, issue: str, authorized_writes: bool = False) -> dict[str, Any]:
        """Compatibility entry point for the same Autonomous fixing a problem."""
        return self.execute(
            objective=issue,
            mode="fix",
            authorized_writes=authorized_writes,
            metadata={"requested_capability": "repair"},
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
