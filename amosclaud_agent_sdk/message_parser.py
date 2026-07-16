"""Typed, defensive parsing for Amosclaud conversation messages."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

Role = Literal["user", "assistant", "system", "tool"]


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str
    created_at: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_message(value: Message | dict[str, Any]) -> Message:
    if isinstance(value, Message):
        return value
    if not isinstance(value, dict):
        raise TypeError("message must be a mapping")
    role = str(value.get("role") or "").lower()
    if role not in {"user", "assistant", "system", "tool"}:
        raise ValueError("message role must be user, assistant, system, or tool")
    content = str(value.get("content") or "").strip()
    if not content:
        raise ValueError("message content is required")
    metadata = value.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError("message metadata must be an object")
    created_at = str(value.get("created_at") or datetime.now(timezone.utc).isoformat())
    return Message(role=role, content=content, created_at=created_at, metadata=dict(metadata))
