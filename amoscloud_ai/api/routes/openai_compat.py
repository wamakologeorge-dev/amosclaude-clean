"""OpenAI-compatible API surface backed by Amosclaud.

Clients must set their base URL to the Amosclaud deployment. Amosclaud API keys
are not credentials for api.openai.com and are only accepted by this gateway.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai import provider
from amoscloud_ai.agent_tokens import credit_tokens, debit_tokens, ensure_agent_schema, key_hash, now
from amoscloud_ai.api.routes.auth import _connect

router = APIRouter(prefix="/v1", tags=["openai-compatible"])


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=200_000)


class ChatCompletionRequest(BaseModel):
    model: str = Field(default="gpt-4.1-mini", min_length=1, max_length=100)
    messages: list[ChatMessage] = Field(min_length=1, max_length=100)
    stream: bool = False


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _authenticate(authorization: str | None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="A valid Amosclaud API key is required")
    raw = authorization.removeprefix("Bearer ").strip()
    if not raw:
        raise HTTPException(status_code=401, detail="A valid Amosclaud API key is required")

    with _connect() as db:
        ensure_agent_schema(db)
        row = db.execute(
            """SELECT k.id,k.user_id,w.balance,'provider' AS key_type
               FROM agent_api_keys k
               LEFT JOIN agent_token_wallets w ON w.user_id=k.user_id
               WHERE k.key_hash=? AND k.revoked_at IS NULL""",
            (key_hash(raw),),
        ).fetchone()
        if row:
            db.execute("UPDATE agent_api_keys SET last_used_at=? WHERE id=?", (now(), row["id"]))
            db.commit()
            return dict(row)

        # Autonomous website keys are deliberately accepted by the compatible
        # gateway so one Amosclaud key can operate both the agent and model API.
        try:
            row = db.execute(
                """SELECT k.id,k.user_id,w.balance,'autonomous' AS key_type
                   FROM autonomous_api_keys k
                   LEFT JOIN agent_token_wallets w ON w.user_id=k.user_id
                   WHERE k.key_hash=? AND k.revoked_at IS NULL""",
                (_sha256(raw),),
            ).fetchone()
        except Exception:
            row = None
        if not row:
            raise HTTPException(status_code=401, detail="Amosclaud API key is invalid or revoked")
        used_at = datetime.now(timezone.utc).isoformat()
        db.execute("UPDATE autonomous_api_keys SET last_used_at=? WHERE id=?", (used_at, row["id"]))
        db.commit()
        return dict(row)


@router.get("/models")
def list_models(authorization: str | None = Header(default=None)) -> dict:
    _authenticate(authorization)
    configured = os.getenv("AMOSCLAUD_OPENAI_COMPAT_MODELS", "gpt-4.1-mini,amosclaud-agent")
    models = [name.strip() for name in configured.split(",") if name.strip()]
    return {
        "object": "list",
        "data": [
            {"id": model, "object": "model", "created": 0, "owned_by": "amosclaud"}
            for model in models
        ],
    }


@router.post("/chat/completions")
def chat_completions(
    body: ChatCompletionRequest,
    authorization: str | None = Header(default=None),
) -> dict:
    if body.stream:
        raise HTTPException(status_code=400, detail="Streaming is not enabled on this gateway yet")
    credential = _authenticate(authorization)
    allowed = {
        name.strip()
        for name in os.getenv("AMOSCLAUD_OPENAI_COMPAT_MODELS", "gpt-4.1-mini,amosclaud-agent").split(",")
        if name.strip()
    }
    if body.model not in allowed:
        raise HTTPException(status_code=404, detail=f"Model '{body.model}' is not available")

    cost = max(1, int(os.getenv("AMOSCLAUD_AGENT_CREDITS_PER_REQUEST", "1")))
    request_id = "chatcmpl-" + uuid.uuid4().hex
    with _connect() as db:
        if not debit_tokens(db, int(credential["user_id"]), cost, reference=request_id):
            raise HTTPException(status_code=402, detail={"code": "agent_tokens_required", "purchase_url": "/plans"})

    messages = [message.model_dump() for message in body.messages]
    system = "\n".join(message["content"] for message in messages if message["role"] == "system")
    system = system or "You are Amosclaud, a professional engineering agent."
    history = [message for message in messages if message["role"] != "system"]
    try:
        result = provider.reply(history, system)
        if result.status != "ready":
            raise RuntimeError("Owner model runtime is unavailable")
    except Exception:
        with _connect() as db:
            credit_tokens(db, int(credential["user_id"]), cost, reason="agent_request_refund", reference=request_id)
        raise HTTPException(status_code=503, detail="Amosclaud model gateway is unavailable")

    return {
        "id": request_id,
        "object": "chat.completion",
        "created": int(datetime.now(timezone.utc).timestamp()),
        "model": body.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.reply},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "amosclaud": {"credits_used": cost, "key_type": credential["key_type"]},
    }
