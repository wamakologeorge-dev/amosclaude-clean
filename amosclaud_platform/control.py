"""Single command control plane for the existing Amosclaud services.

This module does not reimplement the database, repository service, Agent, fixer,
AmoModel, Byte bus, credential authority, metrics, or FastAPI application. It
initializes and checks those existing components, then reports one truthful
platform status.
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
        "api_key_manager": "api_key_manager.main",
        "byte_bus": "Amosclaud.platform_bus",
        "database": "database.session",
        "metrics": "amosclaud_metrics.server",
        "repository": "repository.connector",
    }

    def __init__(self, *, repository_root: str | Path | None = None) -> None:
        self.repository_root = repository_root

    @staticmethod
    def _import_check(name: str, module_name: str) -> ServiceCheck:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            return ServiceCheck(name, "failed", f"{type(exc).__name__}: {exc}")
        return ServiceCheck(name, "ready", module_name)

    @staticmethod
    def _secret_check(name: str, env_name: str, minimum: int, *, required: bool) -> ServiceCheck:
        value = os.getenv(env_name, "")
        ready = len(value) >= minimum
        return ServiceCheck(
            name,
            "ready" if ready else ("failed" if required else "warning"),
            "configured" if ready else f"{env_name} must contain at least {minimum} characters",
            required=required,
        )

    def initialize(self) -> PlatformReport:
        checks: list[ServiceCheck] = []
        try:
            create_database()
            checks.append(ServiceCheck("shared_database", "ready", "schema initialized"))
        except Exception as exc:
            checks.append(ServiceCheck("shared_database", "failed", f"{type(exc).__name__}: {exc}"))

        try:
            connector = RepositoryConnector(root=self.repository_root)
            checks.append(ServiceCheck("repository_storage", "ready", str(connector.root)))
        except Exception as exc:
            checks.append(ServiceCheck("repository_storage", "failed", f"{type(exc).__name__}: {exc}"))

        for name, module_name in self.IMPORT_CHECKS.items():
            checks.append(self._import_check(name, module_name))

        checks.append(
            self._secret_check(
                "byte_bus_secret",
                "AMOSCLAUD_BYTE_BUS_SECRET",
                32,
                required=False,
            )
        )
        checks.append(
            self._secret_check(
                "credential_jwt_secret",
                "AGENT_JWT_SECRET_KEY",
                32,
                required=False,
            )
        )
        checks.append(
            self._secret_check(
                "metrics_token",
                "AMOSCLAUD_METRICS_TOKEN",
                24,
                required=False,
            )
        )

        admin_username = os.getenv("API_KEY_MANAGER_ADMIN_USERNAME", "").strip()
        admin_password = os.getenv("API_KEY_MANAGER_ADMIN_PASSWORD", "")
        credential_admin_ready = bool(admin_username and len(admin_password) >= 12)
        checks.append(
            ServiceCheck(
                "credential_admin",
                "ready" if credential_admin_ready else "warning",
                "configured" if credential_admin_ready else (
                    "API_KEY_MANAGER_ADMIN_USERNAME and a 12+ character "
                    "API_KEY_MANAGER_ADMIN_PASSWORD are required before starting the service"
                ),
                required=False,
            )
        )

        try:
            from api_key_manager.database import ensure_schema

            ensure_schema()
            checks.append(ServiceCheck("credential_database", "ready", "schema initialized"))
        except Exception as exc:
            checks.append(
                ServiceCheck(
                    "credential_database",
                    "failed",
                    f"{type(exc).__name__}: {exc}",
                    required=False,
                )
            )

        try:
            from amosclaud_metrics.platform import collect_platform_snapshot

            snapshot = collect_platform_snapshot()
            down = sorted(name for name, state in snapshot["services"].items() if not state.get("up"))
            checks.append(
                ServiceCheck(
                    "platform_observability",
                    "ready" if snapshot["status"] == "healthy" else "warning",
                    "all required services observable" if not down else f"attention: {', '.join(down)}",
                    required=False,
                )
            )
        except Exception as exc:
            checks.append(
                ServiceCheck(
                    "platform_observability",
                    "failed",
                    f"{type(exc).__name__}: {exc}",
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
