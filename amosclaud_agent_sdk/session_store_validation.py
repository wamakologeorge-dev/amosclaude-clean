"""Validate persisted session documents before use or migration."""
from __future__ import annotations

from typing import Any

from .sessions import AgentSession


def validate_session_document(value: dict[str, Any]) -> list[str]:
    """Validate a raw session dict without raising exceptions.

    Attempts to construct an :class:`~amosclaud_agent_sdk.sessions.AgentSession`
    from ``value`` and collects any structural errors into a list.

    Args:
        value: Raw dict to validate (typically loaded from a ``.json`` file).

    Returns:
        A list of human-readable error strings. An empty list means the document
        is valid and can be safely passed to
        :meth:`~amosclaud_agent_sdk.sessions.AgentSession.from_dict`.
    """
    errors: list[str] = []
    try:
        session = AgentSession.from_dict(value)
        if not session.id:
            errors.append("session id is required")
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(str(exc))
    return errors
