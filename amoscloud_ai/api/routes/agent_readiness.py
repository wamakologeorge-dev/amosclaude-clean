from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter

from amoscloud_ai import provider
from amoscloud_ai.core.tokens import AmosclaudTokenService
from amoscloud_ai.core.workspace import WorkspaceEngine

router = APIRouter(prefix="/agent", tags=["autonomous-agent"])


@router.get("/readiness")
def agent_readiness() -> dict:
    """Prove that the local agent can access its workspace, token authority, and model."""
    checks: dict[str, dict] = {}

    try:
        workspace = WorkspaceEngine()
        manifest = workspace.manifest()
        checks["workspace"] = {
            "ready": manifest.get("source_of_truth") == "files",
            "root": str(workspace.root),
        }
    except Exception as exc:
        checks["workspace"] = {"ready": False, "detail": f"{type(exc).__name__}: {exc}"}

    try:
        token_db = Path(os.getenv("AMOSCLAUD_CORE_DB", "/data/amosclaud-core.db"))
        AmosclaudTokenService(token_db)
        checks["token_authority"] = {"ready": True, "prefix": "amo_token_"}
    except Exception as exc:
        checks["token_authority"] = {"ready": False, "detail": f"{type(exc).__name__}: {exc}"}

    checks["model"] = provider.probe()
    ready = all(bool(check.get("ready")) for check in checks.values())
    return {
        "ready": ready,
        "status": "ready" if ready else "starting",
        "agent": "Amosclaud Autonomous Server",
        "provider": "amosclaud",
        "checks": checks,
    }
