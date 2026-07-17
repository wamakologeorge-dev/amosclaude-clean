"""Import portable Amosclaud session JSON without trusting its file paths."""
from __future__ import annotations

import json
from pathlib import Path

from .session_store import SessionStore
from .sessions import AgentSession, save_session


def import_session(source: str | Path, store: SessionStore) -> AgentSession:
    value = json.loads(Path(source).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("session import must contain one JSON object")
    session = AgentSession.from_dict(value)
    store.path(session.id)
    save_session(store, session)
    return session
