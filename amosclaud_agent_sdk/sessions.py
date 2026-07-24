"""High-level durable sessions for multi-turn autonomous work."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .message_parser import Message, parse_message
from .session_store import SessionStore

_CONVERSATION_WINDOW = 12


@dataclass(slots=True)
class AgentSession:
    """An in-memory conversation session with ordered messages and free-form metadata.

    Instances are created via :func:`create_session` and persisted through
    :class:`~amosclaud_agent_sdk.session_store.SessionStore`. Do not construct
    directly from user-supplied data; use :meth:`from_dict` instead.
    """

    id: str
    messages: list[Message] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def append(self, role: str, content: str, metadata: dict[str, Any] | None = None) -> Message:
        """Parse and append one message, updating ``updated_at`` to the current UTC time.

        Args:
            role: One of ``"user"``, ``"assistant"``, ``"system"``, or ``"tool"``.
            content: Non-empty message text.
            metadata: Optional per-message context dict.

        Returns:
            The newly created :class:`~amosclaud_agent_sdk.message_parser.Message`.

        Raises:
            ValueError: If ``role`` is unknown or ``content`` is blank.
        """
        message = parse_message({"role": role, "content": content, "metadata": metadata or {}})
        self.messages.append(message)
        self.updated_at = datetime.now(timezone.utc).isoformat()
        return message

    def to_dict(self) -> dict[str, Any]:
        """Serialize the session to a JSON-safe dict suitable for :class:`SessionStore`."""
        return {
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "messages": [item.to_dict() for item in self.messages],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AgentSession":
        """Reconstruct an ``AgentSession`` from a previously serialized dict.

        Args:
            value: A dict as produced by :meth:`to_dict`.

        Raises:
            KeyError: If ``"id"`` is absent from ``value``.
            ValueError: If any embedded message fails validation.
        """
        return cls(
            id=str(value["id"]),
            created_at=str(value.get("created_at") or ""),
            updated_at=str(value.get("updated_at") or ""),
            metadata=dict(value.get("metadata") or {}),
            messages=[parse_message(item) for item in value.get("messages", [])],
        )


def create_session(
    store: SessionStore,
    *,
    metadata: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> AgentSession:
    """Create a new session and immediately persist it to ``store``.

    Args:
        store: The :class:`SessionStore` that will hold the session file.
        metadata: Arbitrary context attached to the session (not to individual messages).
        session_id: Explicit session ID; a UUID is generated when omitted.

    Returns:
        The newly created and saved :class:`AgentSession`.
    """
    session = AgentSession(id=session_id or str(uuid.uuid4()), metadata=dict(metadata or {}))
    store.save(session.id, session.to_dict())
    return session


def save_session(store: SessionStore, session: AgentSession) -> None:
    """Atomically persist the current state of ``session`` to ``store``."""
    store.save(session.id, session.to_dict())


def load_session(store: SessionStore, session_id: str) -> AgentSession:
    """Load a session from ``store`` by its ID.

    Raises:
        FileNotFoundError: If no session with ``session_id`` exists in ``store``.
    """
    return AgentSession.from_dict(store.load(session_id))
