"""Authenticated Codex-style bridge into the Amosclaud Autonomous runtime.

This route is intentionally separate from browser session authentication. A connector
API key is mapped to an Amosclaud account, the task is executed to a terminal result,
and the same verified reply/checks/logs are returned to the caller.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes import auth
from amoscloud_ai.autonomous_server import run_autonomous_server
from amoscloud_ai.models import PipelineStatus

router = APIRouter(prefix="/connectors/codex", tags=["codex-connector"])

ALLOWED_MODES = {"autonomous-check", "build", "fix", "deploy", "monitor"}


class CodexRunRequest(BaseModel):
    objective: str = Field(..., min_length=1, max_length=12000)
    mode: str = "autonomous-check"
    branch: str = Field(default="main", pattern=r"^[A-Za-z0-9._/-]+$")
    conversation_id: str | None = Field(default=None, max_length=128)
    use_model: bool = False
    apply_changes: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class CodexRunResponse(BaseModel):
    accepted: bool
    run_id: str
    conversation_id: str
    user_id: int
    mode: str
    branch: str
    objective: str
    status: PipelineStatus
    reply: str
    checks: list[dict[str, Any]]
    logs: list[str]
    model_requested: bool
    model_used: bool
    rollback_recommended: bool = False


def _configured_key() -> str:
    return os.getenv("AMOSCLAUD_API_KEY", "").strip()


def _provided_key(authorization: str | None, x_api_key: str | None) -> str:
    if x_api_key:
        return x_api_key.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def _authenticate_connector(authorization: str | None, x_api_key: str | None) -> dict[str, Any]:
    expected = _configured_key()
    supplied = _provided_key(authorization, x_api_key)
    if not expected:
        raise HTTPException(status_code=503, detail="AMOSCLAUD_API_KEY is not configured")
    if not supplied or not hmac.compare_digest(
        hashlib.sha256(supplied.encode()).digest(),
        hashlib.sha256(expected.encode()).digest(),
    ):
        raise HTTPException(status_code=401, detail="Invalid Amosclaud connector API key")

    user_id = int(os.getenv("AMOSCLAUD_API_USER_ID", "1"))
    with auth._connect() as db:
        row = db.execute(
            "SELECT id,name,email,is_admin,provider FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=403, detail=f"Configured connector user {user_id} does not exist")
    return dict(row)


@router.post("/run", response_model=CodexRunResponse, summary="Run a Codex-style Autonomous task to completion")
async def run_codex_task(
    body: CodexRunRequest,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> CodexRunResponse:
    user = _authenticate_connector(authorization, x_api_key)
    mode = body.mode.strip().lower()
    if mode not in ALLOWED_MODES:
        raise HTTPException(status_code=422, detail=f"Mode must be one of: {', '.join(sorted(ALLOWED_MODES))}")

    run_id = str(uuid.uuid4())
    conversation_id = body.conversation_id or str(uuid.uuid4())
    metadata = dict(body.metadata)
    metadata.update(
        {
            "connector": "codex",
            "source": "amosclaud-autonomous-codex-connector",
            "user_id": user["id"],
            "user_name": user["name"],
            "conversation_id": conversation_id,
            "branch": body.branch,
            "use_agent": bool(body.use_model),
            "apply_changes": bool(body.apply_changes or mode == "fix"),
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    # Execute synchronously so Codex receives the terminal verified result rather
    # than a queued acknowledgement that requires a second manual polling step.
    result = run_autonomous_server(mode, body.objective.strip(), metadata)
    checks = [
        {"name": item.name, "status": item.status, "summary": item.summary, "details": item.details}
        for item in result.checks
    ]
    model_used = any(item.name.startswith("agentic-cloud-core") or item.name.startswith("agent-") for item in result.checks)
    rollback_recommended = mode == "deploy" and result.status == PipelineStatus.FAILED

    return CodexRunResponse(
        accepted=True,
        run_id=run_id,
        conversation_id=conversation_id,
        user_id=user["id"],
        mode=mode,
        branch=body.branch,
        objective=body.objective.strip(),
        status=result.status,
        reply=result.reply,
        checks=checks,
        logs=result.logs,
        model_requested=body.use_model,
        model_used=model_used,
        rollback_recommended=rollback_recommended,
    )
