"""Safe, explicit mutations for locally owned sessions."""
from __future__ import annotations

from typing import Any

from .session_store import SessionStore
from .sessions import AgentSession, load_session, save_session


def update_metadata(store: SessionStore, session_id: str, changes: dict[str, Any]) -> AgentSession:
    session = load_session(store, session_id)
    session.metadata.update(changes)
    save_session(store, session)
    return session


def truncate_messages(store: SessionStore, session_id: str, keep: int) -> AgentSession:
    if keep < 0:
        raise ValueError("keep must be non-negative")
    session = load_session(store, session_id)
    session.messages = session.messages[-keep:] if keep else []
    save_session(store, session)
    return session
