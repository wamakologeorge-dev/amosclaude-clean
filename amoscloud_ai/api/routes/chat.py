"""Shared chat API for the Amosclaud web dashboard and Android application."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import APIRouter, HTTPException

from amoscloud_ai.models import AgentCapabilityResponse, ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])

_MAX_HISTORY_TURNS = 20
_conversations: dict[str, list[dict[str, str]]] = defaultdict(list)
_conversation_lock = Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _repository_instructions() -> str:
    """Return the repository guidance available to the engineering agent."""
    root = _repository_root()
    parts: list[str] = []
    for filename in ("AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", "README.md"):
        path = root / filename
        if path.is_file():
            try:
                parts.append(f"--- {filename} ---\n{path.read_text(encoding='utf-8')[:12000]}")
            except OSError:
                continue
    return "\n\n".join(parts) or "No repository instruction files were found."


def _system_prompt() -> str:
    return """You are Amosclaud, George Wamakolo's AI engineering partner. You help developers
build applications, inspect repositories, plan fixes, run appropriate checks, deploy through
approved infrastructure, and monitor production. Be direct, accurate, and explicit when an
operation needs a connected repository or human approval. Do not claim that code was edited,
tested, pushed, or deployed unless tools confirmed it. The current first-party client is
connected to the Amosclaud platform repository. Follow these repository instructions:\n\n""" + _repository_instructions()


def _fallback_reply(message: str) -> str:
    return (
        "Amosclaud is online and ready to help with repository analysis, implementation plans, "
        "testing, Railway deployments, and monitoring. Configure ANTHROPIC_API_KEY in the "
        "service environment to enable live AI responses. Your request was received: "
        f"{message}"
    )


def _anthropic_reply(history: list[dict[str, str]]) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _fallback_reply(history[-1]["content"])

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
            max_tokens=1200,
            system=_system_prompt(),
            messages=[{"role": turn["role"], "content": turn["content"]} for turn in history],
        )
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()
        return text or "I could not produce a response. Please try again."
    except Exception:
        # Keep the Android client useful during a provider outage without exposing provider details.
        return _fallback_reply(history[-1]["content"])


@router.post("/api/chat", response_model=ChatResponse, summary="Talk to Amosclaud")
async def chat(body: ChatRequest) -> ChatResponse:
    """Return a repository-aware engineering response for either first-party client."""
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="message must not be empty")

    session_id = body.session_id or str(uuid.uuid4())
    with _conversation_lock:
        history = _conversations[session_id]
        history.append({"role": "user", "content": message})
        history[:] = history[-_MAX_HISTORY_TURNS:]
        request_history = list(history)

    reply = await asyncio.to_thread(_anthropic_reply, request_history)
    with _conversation_lock:
        _conversations[session_id].append({"role": "assistant", "content": reply})
        _conversations[session_id][:] = _conversations[session_id][-_MAX_HISTORY_TURNS:]

    return ChatResponse(
        reply=reply,
        session_id=session_id,
        timestamp=_now(),
        provider="anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "offline",
    )


@router.get("/api/chat/history/{session_id}", summary="Get a chat session")
async def chat_history(session_id: str) -> dict[str, Any]:
    with _conversation_lock:
        history = list(_conversations.get(session_id, []))
    return {"session_id": session_id, "history": history}


@router.delete("/api/chat/history/{session_id}", status_code=204, summary="Clear a chat session")
async def clear_chat_history(session_id: str) -> None:
    with _conversation_lock:
        _conversations.pop(session_id, None)


@router.get("/api/capabilities", response_model=AgentCapabilityResponse)
async def capabilities() -> AgentCapabilityResponse:
    return AgentCapabilityResponse(
        name="Amosclaud",
        version="1.0.0",
        capabilities=[
            "ai_assisted_engineering",
            "repository_instruction_analysis",
            "ci_cd_automation",
            "railway_deployment",
            "health_monitoring",
            "github_integration",
        ],
        repository_scope="wamakologeorge-dev/amosclaude-clean",
        execution_mode="connected-agent",
    )
