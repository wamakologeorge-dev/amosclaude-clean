"""Unified backend service registry for Amosclaud Autonomous."""
from __future__ import annotations

import importlib.util
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from amoscloud_ai import provider


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


def _model_probe() -> dict[str, Any]:
    try:
        result = provider.probe()
    except Exception as exc:
        return {
            "ready": False,
            "provider": "amosclaud",
            "runtime": "unavailable",
            "model": os.getenv("AMOSCLAUD_MODEL", "amosclaud-folder-v1"),
            "detail": f"{type(exc).__name__}: {exc}",
        }
    return dict(result)


def service_registry(model_check: dict[str, Any] | None = None) -> list[ModelService]:
    model_check = model_check or _model_probe()
    model_ready = bool(model_check.get("ready"))
    model_detail = str(model_check.get("detail") or "model probe did not return detail")

    data_root = Path(os.getenv("AMOSCLAUD_DATA_DIR", "data"))
    writable = True
    try:
        data_root.mkdir(parents=True, exist_ok=True)
        probe_path = data_root / ".amosclaud-service-probe"
        probe_path.write_text("ok", encoding="utf-8")
        probe_path.unlink(missing_ok=True)
    except OSError:
        writable = False

    pytest_ready = bool(shutil.which("python")) and _module("pytest")
    return [
        ModelService("agent-1-receive", "Receive Engine", "accept and normalize objectives", True, True, "API objective intake ready"),
        ModelService("agent-2-perceive", "Perception Engine", "inspect repository and runtime evidence", True, True, "repository scanner ready"),
        ModelService("agent-3-model", "Model Planning Service", "create structured safe plans", True, model_ready, model_detail),
        ModelService("agent-4-action", "Controlled Action Engine", "apply authorized workspace changes", True, writable, "workspace storage writable" if writable else "workspace storage is not writable"),
        ModelService("agent-5-verify", "Verification Engine", "compile and test changed code", True, pytest_ready, "Python and pytest ready" if pytest_ready else "pytest is not installed"),
        ModelService("memory", "Agent Memory Service", "store repository lessons and run evidence", True, writable, "memory storage ready" if writable else "memory storage unavailable"),
        ModelService("logs", "Model Log Service", "record structured engine events", True, writable, "structured logging ready" if writable else "log storage unavailable"),
    ]


def readiness() -> dict[str, Any]:
    model_check = _model_probe()
    services = service_registry(model_check)
    required = [service for service in services if service.required]
    workspace_ready = next((service.ready for service in services if service.id == "agent-4-action"), False)
    checks = {
        "workspace": {"ready": workspace_ready, "detail": "controlled workspace is writable" if workspace_ready else "controlled workspace is not writable"},
        "token_authority": {"ready": True, "detail": "Amosclaud key authority is available"},
        "model": model_check,
    }
    ready = all(service.ready for service in required) and all(bool(check.get("ready")) for check in checks.values())
    return {
        "ready": ready,
        "active_model": os.getenv("AMOSCLAUD_MODEL", "amosclaud-folder-v1"),
        "checks": checks,
        "services": [service.to_dict() for service in services],
        "ready_count": sum(service.ready for service in services),
        "total_count": len(services),
    }
