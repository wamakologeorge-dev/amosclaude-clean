"""Deterministic public summaries of Agent SDK sessions."""
from __future__ import annotations

from typing import Any

from .sessions import AgentSession


def summarize_session(session: AgentSession, preview_chars: int = 160) -> dict[str, Any]:
    users = [item for item in session.messages if item.role == "user"]
    assistants = [item for item in session.messages if item.role == "assistant"]
    latest = session.messages[-1].content[:preview_chars] if session.messages else ""
    return {
        "id": session.id,
        "messages": len(session.messages),
        "user_messages": len(users),
        "assistant_messages": len(assistants),
        "latest_preview": latest,
        "updated_at": session.updated_at,
    }
