"""Persisted AmoModel state and audit records."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

VALID_STATES = {"off", "starting", "ready", "busy", "degraded", "stopping", "failed"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class RuntimeState:
    state: str = "off"
    version: str = "0.1.0"
    updated_at: str = field(default_factory=utc_now)
    services: dict[str, str] = field(default_factory=dict)
    last_error: str | None = None
    executions: int = 0
    audit: list[dict[str, Any]] = field(default_factory=list)


class StateStore:
    """Small JSON state store with atomic replacement and bounded audit history."""

    def __init__(self, path: Path | None = None) -> None:
        configured = os.getenv("AMOMODEL_STATE_PATH", "").strip()
        self.path = path or Path(configured or "data/amomodel/state.json")
        self._lock = RLock()

    def load(self) -> RuntimeState:
        with self._lock:
            if not self.path.exists():
                return RuntimeState()
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                state = str(payload.get("state", "off"))
                if state not in VALID_STATES:
                    state = "failed"
                return RuntimeState(
                    state=state,
                    version=str(payload.get("version", "0.1.0")),
                    updated_at=str(payload.get("updated_at") or utc_now()),
                    services=dict(payload.get("services") or {}),
                    last_error=payload.get("last_error"),
                    executions=int(payload.get("executions") or 0),
                    audit=list(payload.get("audit") or [])[-100:],
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                return RuntimeState(state="failed", last_error=f"State load failed: {exc}")

    def save(self, state: RuntimeState) -> RuntimeState:
        if state.state not in VALID_STATES:
            raise ValueError(f"Invalid AmoModel state: {state.state}")
        with self._lock:
            state.updated_at = utc_now()
            state.audit = state.audit[-100:]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(json.dumps(asdict(state), indent=2, sort_keys=True), encoding="utf-8")
            temporary.replace(self.path)
            return state

    def record(self, state: RuntimeState, event: str, actor: str, detail: str = "") -> RuntimeState:
        state.audit.append({"at": utc_now(), "event": event, "actor": actor, "detail": detail[:1000]})
        return self.save(state)
