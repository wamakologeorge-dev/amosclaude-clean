"""Folder-native AmoModel lifecycle and bounded execution runtime."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any

from .service_graph import ServiceGraph
from .state import RuntimeState, StateStore


class AmoModelRuntime:
    """Governed runtime that persists truthful state and never executes shell commands."""

    def __init__(self, state_path: Path | None = None) -> None:
        self.store = StateStore(state_path)
        self.graph = ServiceGraph()
        self._lock = RLock()

    def status(self) -> dict[str, Any]:
        state = self.store.load()
        return self._snapshot(state)

    def power_on(self, actor: str) -> dict[str, Any]:
        with self._lock:
            state = self.store.load()
            if state.state in {"ready", "busy"}:
                return self._snapshot(state)
            state.state = "starting"
            state.last_error = None
            self.store.record(state, "power_on_started", actor)
            state.services = self.graph.startup()
            state.state = "ready" if self.graph.healthy(state.services) else "degraded"
            self.store.record(state, "power_on_finished", actor, state.state)
            return self._snapshot(state)

    def power_off(self, actor: str) -> dict[str, Any]:
        with self._lock:
            state = self.store.load()
            state.state = "stopping"
            self.store.record(state, "power_off_started", actor)
            state.services = self.graph.shutdown()
            state.state = "off"
            state.last_error = None
            self.store.record(state, "power_off_finished", actor)
            return self._snapshot(state)

    def restart(self, actor: str) -> dict[str, Any]:
        with self._lock:
            self.power_off(actor)
            result = self.power_on(actor)
            state = self.store.load()
            self.store.record(state, "restart_finished", actor)
            return result

    def execute(self, actor: str, objective: str, wake: bool = True) -> dict[str, Any]:
        clean = objective.strip()
        if not clean:
            raise ValueError("objective must not be empty")
        with self._lock:
            state = self.store.load()
            if state.state == "off" and wake:
                self.power_on(actor)
                state = self.store.load()
            if state.state != "ready":
                raise RuntimeError(f"AmoModel is not ready; current state is {state.state}")
            state.state = "busy"
            self.store.record(state, "execution_started", actor, clean)
            # First experiment: deterministic, inspectable execution planning only.
            result = {
                "objective": clean,
                "accepted": True,
                "engine": "folder-native-deterministic",
                "message": "AmoModel accepted the objective through its governed service graph.",
                "service_evidence": self.graph.evidence(state.services),
            }
            state.executions += 1
            state.state = "ready"
            self.store.record(state, "execution_finished", actor, clean)
            result["runtime"] = self._snapshot(state)
            return result

    def _snapshot(self, state: RuntimeState) -> dict[str, Any]:
        return {
            "name": "AmoModel",
            "version": state.version,
            "state": state.state,
            "updated_at": state.updated_at,
            "services": state.services,
            "healthy": state.state == "ready" and self.graph.healthy(state.services),
            "last_error": state.last_error,
            "executions": state.executions,
            "audit": state.audit[-20:],
        }


_RUNTIME: AmoModelRuntime | None = None


def get_runtime() -> AmoModelRuntime:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = AmoModelRuntime()
    return _RUNTIME
