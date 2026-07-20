"""Import portable Amosclaud session JSON without trusting its file paths."""
from __future__ import annotations

import json
from pathlib import Path

from .session_store import SessionStore
from .sessions import AgentSession, save_session


def import_session(source: str | Path, store: SessionStore) -> AgentSession:
    """Import a portable session JSON file into ``store``.

    The session ID is taken from the JSON content, not from the file name, so
    the file can be renamed or transferred between machines safely.

    Args:
        source: Path to a JSON file containing a single session object.
        store: Destination storage backend. The session is saved here after import.

    Returns:
        The imported :class:`~amosclaud_agent_sdk.sessions.AgentSession`.

    Raises:
        ValueError: If the file does not contain a JSON object, or the session
            ID is invalid for ``store``.
        FileNotFoundError: If ``source`` does not exist.
    """
    value = json.loads(Path(source).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("session import must contain one JSON object")
    session = AgentSession.from_dict(value)
    store.path(session.id)
    save_session(store, session)
    return session
