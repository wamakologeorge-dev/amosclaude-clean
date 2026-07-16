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
        outcome["system_identity"] = asdict(self.identity)
        outcome["mission_number"] = self._missions
        outcome["workspace"] = str(self.workspace)
        return outcome

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
