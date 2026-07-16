from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .autonomous_keys import AutonomousKeyStore


@dataclass(slots=True)
class PreflightReport:
    ready: bool
    checks: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "checks": self.checks,
            "errors": self.errors,
            "details": self.details,
        }


def run_preflight(*, require_openai: bool = True) -> PreflightReport:
    config_path = Path(os.getenv("AMOSCLAUD_CODEX_CONFIG", "config/autonomous-codex.toml"))
    workspace = Path(os.getenv("AMOSCLAUD_WORKSPACE", "workspace/projects"))
    key_store = AutonomousKeyStore()
    checks: dict[str, bool] = {}
    errors: list[str] = []
    details: dict[str, Any] = {
        "config_path": str(config_path),
        "workspace": str(workspace),
        "key_store": str(key_store.path),
    }

    checks["config_exists"] = config_path.is_file()
    config: dict[str, Any] = {}
    if checks["config_exists"]:
        try:
            with config_path.open("rb") as handle:
                config = tomllib.load(handle)
            checks["config_valid"] = all(section in config for section in ("agent", "model", "workspace", "permissions"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            checks["config_valid"] = False
            errors.append(f"Invalid autonomous config: {exc}")
    else:
        checks["config_valid"] = False
        errors.append(f"Autonomous config not found: {config_path}")

    try:
        workspace.mkdir(parents=True, exist_ok=True)
        probe = workspace / ".amosclaud-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks["workspace_writable"] = True
    except OSError as exc:
        checks["workspace_writable"] = False
        errors.append(f"Workspace is not writable: {exc}")

    checks["autonomous_key_store"] = key_store.path.is_file()
    if not checks["autonomous_key_store"]:
        errors.append("Generate an Amosclaud autonomous key with amosclaud-autonomous-setup")

    model = os.getenv("AMOSCLAUD_CODEX_MODEL", "").strip()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    checks["model_configured"] = bool(model)
    checks["openai_key_configured"] = bool(api_key) if require_openai else True
    details["model"] = model or None

    if require_openai and not model:
        errors.append("AMOSCLAUD_CODEX_MODEL is not configured")
    if require_openai and not api_key:
        errors.append("OPENAI_API_KEY is not configured")

    ready = all(checks.values())
    return PreflightReport(ready=ready, checks=checks, errors=errors, details=details)


def main() -> None:
    report = run_preflight()
    print(json.dumps(report.as_dict(), indent=2))
    raise SystemExit(0 if report.ready else 1)


if __name__ == "__main__":
    main()
