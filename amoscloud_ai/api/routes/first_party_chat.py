"""First-party Amosclaud chat route.

This router is registered before the legacy compatibility route. It preserves
native repository and PR-agent actions while routing normal inference through
the Amosclaud provider runtime.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from threading import Lock
from typing import Optional

from fastapi import APIRouter, Cookie, Header, HTTPException

from amoscloud_ai import provider
from amoscloud_ai.agent_actions import parse_repository_create_command
from amoscloud_ai.api.routes import chat as legacy_chat
from amoscloud_ai.logger import log
from amoscloud_ai.models import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


def _chat_executor_workers() -> int:
    raw_value = os.getenv("AMOSCLAUD_CHAT_WORKERS", "4").strip()
    try:
        configured = int(raw_value)
    except ValueError:
        configured = 4
    return max(1, min(configured, 8))


_CHAT_EXECUTOR = ThreadPoolExecutor(
    max_workers=_chat_executor_workers(),
    thread_name_prefix="amosclaud-chat",
)
_ACTIVE_SESSIONS: set[str] = set()
_ACTIVE_SESSIONS_LOCK = Lock()


def _claim_session(session_id: str) -> bool:
    with _ACTIVE_SESSIONS_LOCK:
        if session_id in _ACTIVE_SESSIONS:
            return False
        _ACTIVE_SESSIONS.add(session_id)
        return True


def _release_session(session_id: str) -> None:
    with _ACTIVE_SESSIONS_LOCK:
        _ACTIVE_SESSIONS.discard(session_id)


def _chat_timeout_seconds() -> float:
    """Return a bounded web-request timeout for the model runtime."""

    raw_value = os.getenv("AMOSCLAUD_CHAT_TIMEOUT", "45").strip()
    try:
        configured = float(raw_value)
    except ValueError:
        configured = 45.0
    return max(5.0, min(configured, 55.0))


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
    if not _claim_session(session_id):
        raise HTTPException(
            status_code=409,
            detail="A chat request is already running for this session. Wait for it to finish before sending another message.",
        )

    try:
        with legacy_chat._conversation_lock:
            history = legacy_chat._conversations[session_id]
            history.append({"role": "user", "content": message})
            history[:] = history[-legacy_chat._MAX_HISTORY_TURNS :]
            request_history = list(history)

        timeout_seconds = _chat_timeout_seconds()
        provider_call = partial(
            provider.reply,
            request_history,
            legacy_chat._system_prompt(),
            timeout=timeout_seconds,
        )
        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(_CHAT_EXECUTOR, provider_call),
                timeout=timeout_seconds + 1.0,
            )
            reply = result.reply
        except TimeoutError:
            log.warning(
                "Amosclaud model runtime exceeded the workspace chat timeout of %.1f seconds",
                timeout_seconds,
            )
            reply = (
                "Amosclaud reached the platform, but the model runtime did not answer within "
                f"{timeout_seconds:g} seconds. No repository action was performed. "
                "Check the model-service health and try again."
            )
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
    finally:
        _release_session(session_id)


@router.get("/api/provider/status", summary="Get Amosclaud provider status")
async def provider_status(
    x_amosclaud_owner_key: Optional[str] = Header(default=None),
) -> dict[str, object]:
    if not legacy_chat._is_owner(x_amosclaud_owner_key):
        raise HTTPException(status_code=401, detail="Owner authentication is required")
    return provider.status()
