from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path
from typing import Any

from amoscloud_ai.core.tokens import AmosclaudTokenService
from amoscloud_ai.core.workspace import WorkspaceEngine
from amoscloud_ai.provider import reply as provider_reply


async def check_agent_readiness(*, test_model: bool = True) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    try:
        workspace = WorkspaceEngine()
        probe = workspace.root / "logs" / ".agent-readiness"
        probe.write_text("ready", encoding="utf-8")
        probe.unlink(missing_ok=True)
        checks.append({"name": "workspace", "status": "ready", "detail": str(workspace.root)})
    except Exception as exc:
        checks.append({"name": "workspace", "status": "failed", "detail": f"{type(exc).__name__}: {exc}"})

    try:
        db_path = Path(os.getenv("AMOSCLAUD_CORE_DB", "data/amosclaud-core.db"))
        AmosclaudTokenService(db_path)
        with sqlite3.connect(db_path) as db:
            row = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='amo_tokens'"
            ).fetchone()
        if not row:
            raise RuntimeError("Amosclaud token table is unavailable")
        checks.append({"name": "token-authority", "status": "ready", "detail": "amo_token_ authority available"})
    except Exception as exc:
        checks.append({"name": "token-authority", "status": "failed", "detail": f"{type(exc).__name__}: {exc}"})

    model_endpoint = os.getenv("AMOSCLAUD_MODEL_URL", "").strip()
    if not test_model:
        checks.append(
            {
                "name": "model-response",
                "status": "skipped",
                "detail": "Model response test disabled for this request",
            }
        )
    elif not model_endpoint:
        checks.append(
            {
                "name": "model-response",
                "status": "failed",
                "detail": "AMOSCLAUD_MODEL_URL is not configured",
            }
        )
    else:
        try:
            result = await asyncio.to_thread(
                provider_reply,
                [{"role": "user", "content": "Reply with exactly: AMOSCLAUD_AGENT_READY"}],
                "You are the Amosclaud local readiness probe. Follow the user's instruction exactly.",
            )
            response = result.reply.strip()
            if not response:
                raise RuntimeError("Local model returned an empty response")
            checks.append(
                {
                    "name": "model-response",
                    "status": "ready" if result.status == "ready" else "failed",
                    "detail": response[:160],
                    "runtime": result.runtime,
                }
            )
        except Exception as exc:
            checks.append({"name": "model-response", "status": "failed", "detail": f"{type(exc).__name__}: {exc}"})

    ready = all(check["status"] in {"ready", "skipped"} for check in checks)
    return {
        "status": "ready" if ready else "not-ready",
        "agent": "Amosclaud Autonomous Server",
        "provider": "amosclaud",
        "model": os.getenv("AMOSCLAUD_MODEL", "qwen2.5-coder:3b"),
        "checks": checks,
    }
