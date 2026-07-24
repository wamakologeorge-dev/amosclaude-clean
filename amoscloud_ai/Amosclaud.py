from __future__ import annotations

import os
import platform
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from amoscloud_ai import __version__
from amoscloud_ai.config import settings
from amoscloud_ai.core.workspace import WorkspaceEngine


SENSITIVE_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "PRIVATE")


class AmosclaudDashboard:
    """Build a safe metadata snapshot for the Amosclaud owner dashboard.

    The dashboard deliberately exposes platform state, not secret values.
    """

    def __init__(self, workspace: WorkspaceEngine | None = None) -> None:
        self.workspace = workspace or WorkspaceEngine()

    @staticmethod
    def _disk(path: Path) -> dict[str, int]:
        target = path if path.exists() else path.parent
        usage = shutil.disk_usage(target)
        return {"total_bytes": usage.total, "used_bytes": usage.used, "free_bytes": usage.free}

    @staticmethod
    def _configured_environment() -> list[str]:
        visible: list[str] = []
        for name, value in os.environ.items():
            upper = name.upper()
            if not value or any(marker in upper for marker in SENSITIVE_MARKERS):
                continue
            if upper.startswith(("AMOSCLAUD_", "AUTH_", "PASSKEY_", "STORAGE_", "REPOSITORY_")):
                visible.append(name)
        return sorted(visible)

    def snapshot(self) -> dict[str, Any]:
        workspace = self.workspace.summary()
        return {
            "identity": {
                "name": settings.app_name,
                "product": "Amosclaud",
                "edition": os.getenv("AMOSCLAUD_EDITION", "Community"),
                "version": __version__,
                "domain": os.getenv("AMOSCLAUD_PUBLIC_DOMAIN", "amosclaud.com"),
                "runtime": "Amosclaud.py",
            },
            "runtime": {
                "status": "operational",
                "environment": settings.environment,
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "operating_system": platform.system(),
                "os_release": platform.release(),
                "architecture": platform.machine(),
                "process_id": os.getpid(),
                "executable": Path(sys.executable).name,
            },
            "agent": {
                "name": "Amosclaud Autonomous Server",
                "language": "Amo Runtime",
                "language_version": "amo 1",
                "model": os.getenv("AMOSCLAUD_MODEL", "qwen2.5-coder:3b"),
                "model_endpoint_configured": bool(os.getenv("AMOSCLAUD_MODEL_URL")),
                "external_ai_keys_enabled": os.getenv("AMOSCLAUD_EXTERNAL_AI_KEYS", "false").lower() == "true",
            },
            "workspace": workspace,
            "storage": {
                "workspace_disk": self._disk(self.workspace.root),
                "workspace_root": str(self.workspace.root),
            },
            "network": {
                "host": settings.host,
                "port": settings.port,
                "access_mode": os.getenv("AMOSCLAUD_ACCESS_MODE", "local"),
                "public_domain": os.getenv("AMOSCLAUD_PUBLIC_DOMAIN", "amosclaud.com"),
                "https_expected": settings.environment.lower() in {"production", "prod"},
            },
            "capabilities": {
                "folder_first_workspace": True,
                "local_agent": True,
                "amo_runtime": True,
                "repository_hosting": True,
                "pipelines": True,
                "deployments": True,
                "vault": True,
                "amosclaud_tokens": True,
                "local_model": True,
                "optional_github_adapter": True,
            },
            "configuration": {
                "visible_variable_names": self._configured_environment(),
                "secrets_redacted": True,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
