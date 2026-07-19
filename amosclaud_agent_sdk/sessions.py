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
    id: str
    messages: list[Message] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def append(self, role: str, content: str, metadata: dict[str, Any] | None = None) -> Message:
        message = parse_message({"role": role, "content": content, "metadata": metadata or {}})
        self.messages.append(message)
        self.updated_at = datetime.now(timezone.utc).isoformat()
        return message

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "messages": [item.to_dict() for item in self.messages],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AgentSession":
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
    session = AgentSession(id=session_id or str(uuid.uuid4()), metadata=dict(metadata or {}))
    store.save(session.id, session.to_dict())
    return session


def save_session(store: SessionStore, session: AgentSession) -> None:
    store.save(session.id, session.to_dict())


def load_session(store: SessionStore, session_id: str) -> AgentSession:
    return AgentSession.from_dict(store.load(session_id))
