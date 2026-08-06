"""OpenAI-compatible API surface backed by Amosclaud.

Clients must set their base URL to the Amosclaud deployment. Amosclaud API keys
are not credentials for api.openai.com and are only accepted by this gateway.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai import provider
from amoscloud_ai.agent_tokens import (
    api_access_is_activated,
    credit_tokens,
    debit_tokens,
    ensure_agent_schema,
    key_hash,
    now,
)
from amoscloud_ai.api.routes.auth import _connect

router = APIRouter(prefix="/v1", tags=["openai-compatible"])


class ChatMessage(BaseModel):
    role: Literal["system", "developer", "user", "assistant"]
    content: str = Field(min_length=1, max_length=200_000)


class ChatCompletionRequest(BaseModel):
    model: str = Field(default="gpt-4.1-mini", min_length=1, max_length=100)
    messages: list[ChatMessage] = Field(min_length=1, max_length=100)
    stream: bool = False


class ResponsesRequest(BaseModel):
    """Supported subset of the OpenAI Responses request contract."""

    model: str = Field(default="amosclaud-agent", min_length=1, max_length=100)
    input: str | list[ChatMessage]
    instructions: str | None = Field(default=None, max_length=200_000)
    stream: bool = False
    max_output_tokens: int | None = Field(default=None, ge=1, le=32_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _payment_required() -> HTTPException:
    return HTTPException(
        status_code=402,
        detail=(
            "Pay with Cash App or Bitcoin and wait for Amosclaud to verify the "
            "payment before using the Amosclaud API."
        ),
    )


def _authenticate(authorization: str | None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="A valid Amosclaud API key is required")
    raw = authorization.removeprefix("Bearer ").strip()
    if not raw:
        raise HTTPException(status_code=401, detail="A valid Amosclaud API key is required")

    with _connect() as db:
        ensure_agent_schema(db)
        row = db.execute(
            """SELECT k.id,k.user_id,w.balance,u.is_admin,'provider' AS key_type
               FROM agent_api_keys k
               JOIN users u ON u.id=k.user_id
               LEFT JOIN agent_token_wallets w ON w.user_id=k.user_id
               WHERE k.key_hash=? AND k.revoked_at IS NULL""",
            (key_hash(raw),),
        ).fetchone()
        if row:
            if not api_access_is_activated(
                db,
                int(row["user_id"]),
                is_admin=bool(row["is_admin"]),
            ):
                raise _payment_required()
            db.execute("UPDATE agent_api_keys SET last_used_at=? WHERE id=?", (now(), row["id"]))
            db.commit()
            return dict(row)

        try:
            row = db.execute(
                """SELECT k.id,k.user_id,w.balance,u.is_admin,'autonomous' AS key_type
                   FROM autonomous_api_keys k
                   JOIN users u ON u.id=k.user_id
                   LEFT JOIN agent_token_wallets w ON w.user_id=k.user_id
                   WHERE k.key_hash=? AND k.revoked_at IS NULL""",
                (_sha256(raw),),
            ).fetchone()
        except Exception:
            row = None
        if not row:
            raise HTTPException(status_code=401, detail="Amosclaud API key is invalid or revoked")
        if not api_access_is_activated(
            db,
            int(row["user_id"]),
            is_admin=bool(row["is_admin"]),
        ):
            raise _payment_required()
        used_at = datetime.now(timezone.utc).isoformat()
        db.execute("UPDATE autonomous_api_keys SET last_used_at=? WHERE id=?", (used_at, row["id"]))
        db.commit()
        return dict(row)


def _allowed_models() -> set[str]:
    return {
        name.strip()
        for name in os.getenv(
            "AMOSCLAUD_OPENAI_COMPAT_MODELS",
            "gpt-4.1-mini,amosclaud-agent",
        ).split(",")
        if name.strip()
    }


def _generate_reply(model: str, messages: list[dict[str, str]]) -> str:
    """Route named OpenAI models to OpenAI using the server-owned credential."""
    if model.startswith("gpt-"):
        upstream_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not upstream_key:
            raise RuntimeError("OpenAI upstream is not configured")
        from openai import OpenAI

        response = OpenAI(api_key=upstream_key).responses.create(
            model=model,
            input=messages,
            store=False,
        )
        text = getattr(response, "output_text", "")
        if not text:
            raise RuntimeError("OpenAI upstream returned no text")
        return text

    system = "\n".join(
        message["content"] for message in messages if message["role"] in {"system", "developer"}
    )
    system = system or "You are Amosclaud, a professional engineering agent."
    history = [
        {"role": message["role"], "content": message["content"]}
        for message in messages
        if message["role"] not in {"system", "developer"}
    ]
    result = provider.reply(history, system)
    if result.status != "ready":
        raise RuntimeError("Owner model runtime is unavailable")
    return result.reply


def _run_credited_request(
    *,
    credential: dict,
    model: str,
    messages: list[dict[str, str]],
    request_id: str,
) -> tuple[str, int]:
    allowed = _allowed_models()
    if model not in allowed:
        raise HTTPException(status_code=404, detail=f"Model '{model}' is not available")

    cost = max(1, int(os.getenv("AMOSCLAUD_AGENT_CREDITS_PER_REQUEST", "1")))
    with _connect() as db:
        if not debit_tokens(db, int(credential["user_id"]), cost, reference=request_id):
            raise HTTPException(
                status_code=402,
                detail={"code": "agent_tokens_required", "purchase_url": "/api-access"},
            )

    try:
        return _generate_reply(model, messages), cost
    except Exception:
        with _connect() as db:
            credit_tokens(
                db,
                int(credential["user_id"]),
                cost,
                reason="agent_request_refund",
                reference=request_id,
            )
        raise HTTPException(status_code=503, detail="Amosclaud model gateway is unavailable")


def _responses_messages(body: ResponsesRequest) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if body.instructions and body.instructions.strip():
        messages.append({"role": "system", "content": body.instructions.strip()})
    if isinstance(body.input, str):
        text = body.input.strip()
        if not text:
            raise HTTPException(status_code=422, detail="input cannot be empty")
        messages.append({"role": "user", "content": text})
    else:
        messages.extend(message.model_dump() for message in body.input)
    return messages


@router.get("/models")
def list_models(authorization: str | None = Header(default=None)) -> dict:
    _authenticate(authorization)
    return {
        "object": "list",
        "data": [
            {"id": model, "object": "model", "created": 0, "owned_by": "amosclaud"}
            for model in sorted(_allowed_models())
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
    request_id = "chatcmpl-" + uuid.uuid4().hex
    messages = [message.model_dump() for message in body.messages]
    reply, cost = _run_credited_request(
        credential=credential,
        model=body.model,
        messages=messages,
        request_id=request_id,
    )

    return {
        "id": request_id,
        "object": "chat.completion",
        "created": int(datetime.now(timezone.utc).timestamp()),
        "model": body.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "amosclaud": {"credits_used": cost, "key_type": credential["key_type"]},
    }


@router.post("/responses")
def responses(
    body: ResponsesRequest,
    authorization: str | None = Header(default=None),
) -> dict:
    """Serve the non-streaming Responses API shape used by modern editor clients."""
    if body.stream:
        raise HTTPException(status_code=400, detail="Streaming is not enabled on this gateway yet")
    credential = _authenticate(authorization)
    response_id = "resp_" + uuid.uuid4().hex
    message_id = "msg_" + uuid.uuid4().hex
    reply, cost = _run_credited_request(
        credential=credential,
        model=body.model,
        messages=_responses_messages(body),
        request_id=response_id,
    )
    return {
        "id": response_id,
        "object": "response",
        "created_at": int(datetime.now(timezone.utc).timestamp()),
        "status": "completed",
        "model": body.model,
        "output": [
            {
                "id": message_id,
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": reply,
                        "annotations": [],
                    }
                ],
            }
        ],
        "output_text": reply,
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        },
        "metadata": body.metadata,
        "amosclaud": {
            "credits_used": cost,
            "key_type": credential["key_type"],
        },
    }
