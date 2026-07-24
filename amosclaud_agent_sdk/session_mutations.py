"""Safe, explicit mutations for locally owned sessions."""
from __future__ import annotations

from typing import Any

from .session_store import SessionStore
from .sessions import AgentSession, load_session, save_session


def update_metadata(store: SessionStore, session_id: str, changes: dict[str, Any]) -> AgentSession:
    """Merge ``changes`` into the session's metadata dict and persist the result.

    Existing keys are overwritten; keys absent from ``changes`` are preserved.

    Args:
        store: Session storage backend.
        session_id: Target session.
        changes: Key/value pairs to merge into ``session.metadata``.

    Returns:
        The updated :class:`~amosclaud_agent_sdk.sessions.AgentSession`.

    Raises:
        FileNotFoundError: If the session does not exist in ``store``.
    """
    session = load_session(store, session_id)
    session.metadata.update(changes)
    save_session(store, session)
    return session


def truncate_messages(store: SessionStore, session_id: str, keep: int) -> AgentSession:
    """Trim the session's message list to at most ``keep`` trailing messages and persist.

    Useful for controlling storage size or reducing context sent on subsequent turns.
    Pass ``keep=0`` to clear all messages.

    Args:
        store: Session storage backend.
        session_id: Target session.
        keep: Maximum number of messages to retain from the end of the list.

    Returns:
        The updated :class:`~amosclaud_agent_sdk.sessions.AgentSession`.

    Raises:
        ValueError: If ``keep`` is negative.
        FileNotFoundError: If the session does not exist in ``store``.
    """
    if keep < 0:
        raise ValueError("keep must be non-negative")
    session = load_session(store, session_id)
    session.messages = session.messages[-keep:] if keep else []
    save_session(store, session)
    return session
