"""Shared chat API for the Amosclaud web dashboard and Android application."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException

from amoscloud_ai.models import AgentCapabilityResponse, ChatRequest, ChatResponse, RepositoryTaskRequest

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
        "testing, Railway deployments, and monitoring. Configure ANTHROPIC_API_KEY or "
        "OPENAI_API_KEY in the service environment to enable live AI responses. "
        "Your request was received: "
        f"{message}"
    )


def _active_provider() -> str:
    """Return which LLM provider will answer chat requests."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "offline"


def _openai_reply(history: list[dict[str, str]]) -> str:
    """Answer with OpenAI when an OpenAI key is configured."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return _fallback_reply(history[-1]["content"])

    try:
        import httpx

        payload = {
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            "max_tokens": 1200,
            "messages": [{"role": "system", "content": _system_prompt()}]
            + [{"role": turn["role"], "content": turn["content"]} for turn in history],
        }
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        text = (response.json()["choices"][0]["message"]["content"] or "").strip()
        return text or "I could not produce a response. Please try again."
    except Exception:
        # Keep the client useful during a provider outage without exposing provider details.
        return _fallback_reply(history[-1]["content"])


def _anthropic_reply(history: list[dict[str, str]]) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _openai_reply(history)

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
async def chat(
    body: ChatRequest,
    x_amosclaud_owner_key: Optional[str] = Header(default=None),
) -> ChatResponse:
    """Chat normally, or queue an explicit authenticated PR-agent command."""
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="message must not be empty")

    session_id = body.session_id or str(uuid.uuid4())
    if body.start_pr_task:
        # Execution is explicit and owner-authenticated; ordinary chat can never mutate a repository.
        from amoscloud_ai.api.routes.pr_tasks import _require_owner_key, queue_task

        _require_owner_key(x_amosclaud_owner_key)
        task = queue_task(RepositoryTaskRequest(objective=message, base_branch=body.base_branch))
        reply = f"I started PR-agent task {task.task_id} on branch {task.branch}. I will work in an isolated workspace and report its pull request when complete."
        with _conversation_lock:
            _conversations[session_id].extend([
                {"role": "user", "content": message},
                {"role": "assistant", "content": reply},
            ])
            _conversations[session_id][:] = _conversations[session_id][-_MAX_HISTORY_TURNS:]
        return ChatResponse(
            reply=reply,
            session_id=session_id,
            timestamp=_now(),
            provider="pr-agent",
            task_id=task.task_id,
            task_status=task.status.value,
            task_url=f"/api/v1/agent/tasks/{task.task_id}",
        )
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
        provider=_active_provider(),
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
            "owner_authenticated_pr_agent",
            "isolated_concurrent_repository_tasks",
        ],
        repository_scope="wamakologeorge-dev/amosclaude-clean",
        execution_mode="connected-agent",
    )
