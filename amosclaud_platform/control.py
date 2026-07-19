"""Single command control plane for the existing Amosclaud services.

This module does not reimplement the database, repository service, Agent, fixer,
AmoModel, Byte bus, or FastAPI application. It initializes and checks those
existing components, then reports one truthful platform status.
"""
from __future__ import annotations

import importlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from database.session import create_database
from repository import RepositoryConnector


@dataclass(slots=True)
class ServiceCheck:
    name: str
    status: str
    detail: str
    required: bool = True


@dataclass(slots=True)
class PlatformReport:
    status: str
    services: list[ServiceCheck]

    @property
    def healthy(self) -> bool:
        return all(item.status == "ready" for item in self.services if item.required)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "healthy": self.healthy,
            "services": [asdict(item) for item in self.services],
        }

    def render(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=True)


class PlatformControl:
    """Initialize and inspect all authoritative Amosclaud platform components."""

    IMPORT_CHECKS = {
        "api": "amoscloud_ai.main",
        "amomodel": "amomodel.runtime",
        "agent_worker": "agents.codex_agent",
        "agent_sdk": "amosclaud_agent_sdk",
        "byte_bus": "Amosclaud.platform_bus",
        "database": "database.session",
        "repository": "repository.connector",
    }

    def __init__(self, *, repository_root: str | Path | None = None) -> None:
        self.repository_root = repository_root

    @staticmethod
    def _import_check(name: str, module_name: str) -> ServiceCheck:
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # readiness must report import failures truthfully
            return ServiceCheck(name, "failed", f"{type(exc).__name__}: {exc}")
        return ServiceCheck(name, "ready", module_name)

    def initialize(self) -> PlatformReport:
        checks: list[ServiceCheck] = []
        try:
            create_database()
            checks.append(ServiceCheck("shared_database", "ready", "schema initialized"))
        except Exception as exc:
            checks.append(ServiceCheck("shared_database", "failed", f"{type(exc).__name__}: {exc}"))

        try:
            connector = RepositoryConnector(root=self.repository_root)
            checks.append(
                ServiceCheck(
                    "repository_storage",
                    "ready",
                    str(connector.root),
                )
            )
        except Exception as exc:
            checks.append(ServiceCheck("repository_storage", "failed", f"{type(exc).__name__}: {exc}"))

        for name, module_name in self.IMPORT_CHECKS.items():
            checks.append(self._import_check(name, module_name))

        secret = os.getenv("AMOSCLAUD_BYTE_BUS_SECRET", "").strip()
        checks.append(
            ServiceCheck(
                "byte_bus_secret",
                "ready" if len(secret) >= 32 else "warning",
                "configured" if len(secret) >= 32 else "not configured; signed internal bus remains disabled",
                required=False,
            )
        )

        manifest = Path("agents/manifest.json")
        if manifest.is_file():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                checks.append(
                    ServiceCheck(
                        "agent_manifest",
                        "ready",
                        f"{data.get('framework', 'unknown')}:{data.get('agent', 'unknown')}",
                    )
                )
            except Exception as exc:
                checks.append(ServiceCheck("agent_manifest", "failed", f"{type(exc).__name__}: {exc}"))
        else:
            checks.append(ServiceCheck("agent_manifest", "failed", "agents/manifest.json missing"))

        required_ready = all(item.status == "ready" for item in checks if item.required)
        return PlatformReport("ready" if required_ready else "degraded", checks)

    def status(self) -> PlatformReport:
        return self.initialize()

    def doctor(self) -> PlatformReport:
        """Run deterministic readiness checks without modifying repositories."""
        return self.initialize()

    def power_on_amomodel(self, actor: str = "platform-command") -> dict[str, Any]:
        from amomodel.runtime import AmoModelRuntime

        return AmoModelRuntime().power_on(actor)

    def power_off_amomodel(self, actor: str = "platform-command") -> dict[str, Any]:
        from amomodel.runtime import AmoModelRuntime

        return AmoModelRuntime().power_off(actor)
