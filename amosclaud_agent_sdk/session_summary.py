"""Deterministic public summaries of Agent SDK sessions."""
from __future__ import annotations

from typing import Any

from .sessions import AgentSession


def summarize_session(session: AgentSession, preview_chars: int = 160) -> dict[str, Any]:
    """Return a lightweight summary dict for a session without loading full message content.

    Args:
        session: The session to summarise.
        preview_chars: Maximum characters to include in ``latest_preview``.
            Defaults to 160 (one SMS-length snippet).

    Returns:
        A dict with keys:

        - ``id`` — session identifier.
        - ``messages`` — total message count.
        - ``user_messages`` — count of messages with role ``"user"``.
        - ``assistant_messages`` — count of messages with role ``"assistant"``.
        - ``latest_preview`` — truncated content of the last message, or ``""`` if empty.
        - ``updated_at`` — ISO 8601 timestamp of the last modification.
    """
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
