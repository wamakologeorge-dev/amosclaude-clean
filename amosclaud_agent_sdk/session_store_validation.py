"""Validate persisted session documents before use or migration."""
from __future__ import annotations

from typing import Any

from .sessions import AgentSession


def validate_session_document(value: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        session = AgentSession.from_dict(value)
        if not session.id:
            errors.append("session id is required")
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(str(exc))
    return errors
