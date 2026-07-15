"""Unified backend service registry for Amosclaud Autonomous."""
from __future__ import annotations

import importlib.util
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from amoscloud_ai import model_network


@dataclass(frozen=True)
class ModelService:
    id: str
    name: str
    role: str
    required: bool
    ready: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def service_registry() -> list[ModelService]:
    network = model_network.network_status()
    data_root = Path(os.getenv("AMOSCLAUD_DATA_DIR", "data"))
    writable = True
    try:
        data_root.mkdir(parents=True, exist_ok=True)
        probe = data_root / ".amosclaud-service-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError:
        writable = False

    return [
        ModelService("agent-1-receive", "Receive Engine", "accept and normalize objectives", True, True, "API objective intake ready"),
        ModelService("agent-2-perceive", "Perception Engine", "inspect repository and runtime evidence", True, True, "repository scanner ready"),
        ModelService("agent-3-model", "Model Planning Service", "create structured safe plans", True, bool(network.get("ready")), network.get("detail") or f"{network.get('ready_stations', 0)} model station(s) ready"),
        ModelService("agent-4-action", "Controlled Action Engine", "apply authorized workspace changes", True, writable, "workspace storage writable" if writable else "workspace storage is not writable"),
        ModelService("agent-5-verify", "Verification Engine", "compile and test changed code", True, bool(shutil.which("python")) and _module("pytest"), "Python and pytest ready" if _module("pytest") else "pytest is not installed"),
        ModelService("memory", "Agent Memory Service", "store repository lessons and run evidence", True, writable, "memory storage ready" if writable else "memory storage unavailable"),
        ModelService("logs", "Model Log Service", "record structured engine events", True, writable, "structured logging ready" if writable else "log storage unavailable"),
    ]


def readiness() -> dict[str, Any]:
    services = service_registry()
    required = [service for service in services if service.required]
    return {
        "ready": all(service.ready for service in required),
        "active_model": os.getenv("AMOSCLAUD_MODEL", "amosclaud-folder-v1"),
        "services": [service.to_dict() for service in services],
        "ready_count": sum(service.ready for service in services),
        "total_count": len(services),
    }
