"""Canonical Amosclaud OS kernel.

This module is the single composition root for Autonomous execution. UI routes,
APIs, background jobs, Mini Autonomous, model services, and future OS layers
must call this kernel instead of constructing independent brains.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any

from src.agent.actions import AutonomousOrchestrator, AutonomousTask


@dataclass(frozen=True)
class SystemIdentity:
    product: str = "Amosclaud OS"
    driver: str = "Amosclaud Autonomous"
    architecture: str = "single-autonomous-kernel"
    authority: str = "founder-governed"
    version: str = "3.0.0"


class AutonomousKernel:
    """The one head driver for all Amosclaud operating-system capabilities."""

    def __init__(self, workspace: Path | str = ".") -> None:
        self.workspace = Path(workspace).resolve()
        self.identity = SystemIdentity()
        self._lock = RLock()
        self._orchestrator = AutonomousOrchestrator(self.workspace)
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
        """Execute one governed mission through the canonical Autonomous brain."""
        task = AutonomousTask(
            objective=objective,
            mode=mode,
            authorized_writes=authorized_writes,
            metadata={
                "system": self.identity.product,
                "driver": self.identity.driver,
                "architecture": self.identity.architecture,
                **dict(metadata or {}),
            },
        )
        with self._lock:
            self._missions += 1
            outcome = self._orchestrator.run(task).to_dict()
        return self._stamp(outcome)

    def assist(
        self,
        *,
        message: str,
        evidence: list[str] | None = None,
        result_locations: list[str] | None = None,
        execute: bool = False,
        authorized_writes: bool = False,
    ) -> dict[str, Any]:
        """Answer or execute through the official Amosclaud Agent Assistant."""
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
        """Send a bounded repair mission to Mini Autonomous through the same kernel."""
        from src.agent.mini_autonomous import run_mini_autonomous

        with self._lock:
            self._missions += 1
            result = run_mini_autonomous(
                issue,
                workspace=str(self.workspace),
                authorized_writes=authorized_writes,
            )
        return self._stamp(result)

    def _stamp(self, result: dict[str, Any]) -> dict[str, Any]:
        stamped = dict(result)
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
            "entry_points": [
                "assistant",
                "engineering-loop",
                "mini-autonomous",
                "agent-operations",
                "mission-control",
                "model-router",
                "recovery-doctor",
                "learning-academy",
            ],
        }


_KERNELS: dict[str, AutonomousKernel] = {}
_KERNELS_LOCK = RLock()


def get_autonomous_kernel(workspace: Path | str = ".") -> AutonomousKernel:
    """Return one process-wide kernel per resolved workspace."""
    key = str(Path(workspace).resolve())
    with _KERNELS_LOCK:
        kernel = _KERNELS.get(key)
        if kernel is None:
            kernel = AutonomousKernel(key)
            _KERNELS[key] = kernel
        return kernel
