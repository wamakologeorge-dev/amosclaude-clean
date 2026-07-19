"""Local, side-effect-free metrics for the unified Amosclaud platform."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

from sqlalchemy import func, select


def _module_ready(module: str) -> float:
    return 1.0 if importlib.util.find_spec(module) is not None else 0.0


def _database_snapshot() -> tuple[dict[str, float], dict[str, Any]]:
    metrics: dict[str, float] = {
        "amosclaud_platform_database_up": 0.0,
        "amosclaud_repositories_total": 0.0,
        "amosclaud_autonomous_jobs_total": 0.0,
        "amosclaud_autonomous_jobs_queued": 0.0,
        "amosclaud_autonomous_jobs_running": 0.0,
        "amosclaud_autonomous_jobs_passed": 0.0,
        "amosclaud_autonomous_jobs_failed": 0.0,
        "amosclaud_ci_pipelines_total": 0.0,
        "amosclaud_ci_pipelines_running": 0.0,
        "amosclaud_ci_pipelines_passed": 0.0,
        "amosclaud_ci_pipelines_failed": 0.0,
    }
    service: dict[str, Any] = {"up": False}
    try:
        from database.models import AutonomousJob, CIPipeline, Repository
        from database.session import create_database, session_scope

        create_database()
        with session_scope() as db:
            metrics["amosclaud_repositories_total"] = float(
                db.scalar(select(func.count()).select_from(Repository)) or 0
            )
            metrics["amosclaud_autonomous_jobs_total"] = float(
                db.scalar(select(func.count()).select_from(AutonomousJob)) or 0
            )
            metrics["amosclaud_ci_pipelines_total"] = float(
                db.scalar(select(func.count()).select_from(CIPipeline)) or 0
            )
            for status in ("queued", "inspecting", "repairing", "verifying", "passed", "failed"):
                count = db.scalar(
                    select(func.count()).select_from(AutonomousJob).where(AutonomousJob.status == status)
                ) or 0
                bucket = "running" if status in {"inspecting", "repairing", "verifying"} else status
                key = f"amosclaud_autonomous_jobs_{bucket}"
                metrics[key] = metrics.get(key, 0.0) + float(count)
            for status in ("running", "passed", "failed"):
                count = db.scalar(
                    select(func.count()).select_from(CIPipeline).where(CIPipeline.status == status)
                ) or 0
                metrics[f"amosclaud_ci_pipelines_{status}"] = float(count)
        metrics["amosclaud_platform_database_up"] = 1.0
        service = {"up": True}
    except Exception as exc:  # metrics must degrade instead of taking down the server
        service = {"up": False, "error": type(exc).__name__}
    return metrics, service


def collect_platform_snapshot() -> dict[str, Any]:
    """Return one safe snapshot for control-plane and worker readiness."""
    metrics, database_service = _database_snapshot()

    repository_root = Path(
        os.getenv("AMOSCLAUD_REPOSITORIES_ROOT", os.getenv("REPOSITORY_ROOT", "data/repositories"))
    ).expanduser()
    repository_up = repository_root.exists() and repository_root.is_dir()
    manifest = Path("agents/manifest.json")
    manifest_up = manifest.is_file()
    byte_secret = os.getenv("AMOSCLAUD_BYTE_BUS_SECRET", "").strip()
    jwt_secret = os.getenv("AGENT_JWT_SECRET_KEY", "").strip()
    credential_admin = bool(
        os.getenv("API_KEY_MANAGER_ADMIN_USERNAME", "").strip()
        and os.getenv("API_KEY_MANAGER_ADMIN_PASSWORD", "").strip()
    )

    services: dict[str, dict[str, Any]] = {
        "platform_database": database_service,
        "repository_storage": {"up": repository_up, "path": str(repository_root)},
        "api_gateway": {"up": bool(_module_ready("amoscloud_ai.main"))},
        "amomodel": {"up": bool(_module_ready("amomodel.runtime"))},
        "autonomous_worker": {"up": bool(_module_ready("agents.codex_agent") and manifest_up)},
        "fixer_worker": {"up": bool(_module_ready("agents.codex_agent") and manifest_up)},
        "agent_sdk": {"up": bool(_module_ready("amosclaud_agent_sdk"))},
        "repository_connector": {"up": bool(_module_ready("repository.connector"))},
        "credential_authority": {
            "up": bool(_module_ready("api_key_manager.main") and len(jwt_secret) >= 32 and credential_admin)
        },
        "byte_bus": {"up": bool(_module_ready("Amosclaud.platform_bus") and len(byte_secret) >= 32)},
        "metrics": {"up": True},
    }

    for name, state in services.items():
        metrics[f"amosclaud_service_{name}_up"] = 1.0 if state.get("up") else 0.0
    metrics["amosclaud_agent_manifest_valid"] = 1.0 if manifest_up else 0.0
    metrics["amosclaud_byte_bus_signing_enabled"] = 1.0 if len(byte_secret) >= 32 else 0.0
    metrics["amosclaud_credential_authority_configured"] = (
        1.0 if len(jwt_secret) >= 32 and credential_admin else 0.0
    )

    required = (
        "platform_database",
        "repository_storage",
        "api_gateway",
        "amomodel",
        "autonomous_worker",
        "repository_connector",
        "metrics",
    )
    healthy = all(services[name]["up"] for name in required)
    return {
        "status": "healthy" if healthy else "degraded",
        "services": services,
        "metrics": metrics,
    }
