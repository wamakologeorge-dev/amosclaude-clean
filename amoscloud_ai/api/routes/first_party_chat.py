"""First-party Amosclaud chat route.

This router is registered before the legacy compatibility route. It preserves
native repository and PR-agent actions while routing normal inference through
the Amosclaud provider runtime.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Optional

from fastapi import APIRouter, Cookie, Header, HTTPException

from amoscloud_ai import provider
from amoscloud_ai.agent_actions import parse_repository_create_command
from amoscloud_ai.api.routes import chat as legacy_chat
from amoscloud_ai.logger import log
from amoscloud_ai.models import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


@router.post("/api/chat", response_model=ChatResponse, summary="Talk to Amosclaud")
async def chat(
    body: ChatRequest,
    amos_session: str | None = Cookie(default=None),
    x_amosclaud_owner_key: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> ChatResponse:
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="message must not be empty")

    await legacy_chat._authorize_platform_key(x_api_key, x_amosclaud_owner_key)

    # Preserve verified first-party actions, but expose Amosclaud as the provider.
    if body.start_pr_task or parse_repository_create_command(message) is not None:
        response = await legacy_chat.chat(
            body,
            amos_session=amos_session,
            x_amosclaud_owner_key=x_amosclaud_owner_key,
            x_api_key=x_api_key,
        )
        return response.model_copy(update={"provider": "amosclaud"})

    session_id = body.session_id or str(uuid.uuid4())
    with legacy_chat._conversation_lock:
        history = legacy_chat._conversations[session_id]
        history.append({"role": "user", "content": message})
        history[:] = history[-legacy_chat._MAX_HISTORY_TURNS :]
        request_history = list(history)

    try:
        result = await asyncio.to_thread(provider.reply, request_history, legacy_chat._system_prompt())
        reply = result.reply
    except Exception:
        log.exception("Amosclaud first-party model runtime failed")
        reply = (
            "Amosclaud could not reach its model runtime. The platform action was not completed. "
            "Check the administrator provider status and model-service logs."
        )

    with legacy_chat._conversation_lock:
        legacy_chat._conversations[session_id].append({"role": "assistant", "content": reply})
        legacy_chat._conversations[session_id][:] = legacy_chat._conversations[session_id][
            -legacy_chat._MAX_HISTORY_TURNS :
        ]

    return ChatResponse(
        reply=reply,
        session_id=session_id,
        timestamp=legacy_chat._now(),
        provider="amosclaud",
    )


@router.get("/api/provider/status", summary="Get Amosclaud provider status")
async def provider_status(
    x_amosclaud_owner_key: Optional[str] = Header(default=None),
) -> dict[str, object]:
    if not legacy_chat._is_owner(x_amosclaud_owner_key):
        raise HTTPException(status_code=401, detail="Owner authentication is required")
    return provider.status()
