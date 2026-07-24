"""Typed, defensive parsing for Amosclaud conversation messages."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

Role = Literal["user", "assistant", "system", "tool"]


@dataclass(frozen=True, slots=True)
class Message:
    """An immutable, validated conversation turn.

    Attributes:
        role: Speaker identity — one of ``"user"``, ``"assistant"``,
            ``"system"``, or ``"tool"``.
        content: Non-empty, whitespace-stripped message text.
        created_at: ISO 8601 UTC timestamp; defaults to the current time when
            not supplied by the source dict.
        metadata: Arbitrary per-message context (pipeline IDs, tool results, etc.).
    """

    role: Role
    content: str
    created_at: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dict representation using :func:`dataclasses.asdict`."""
        return asdict(self)


def parse_message(value: Message | dict[str, Any]) -> Message:
    """Validate and coerce a raw dict (or passthrough a ``Message``) into a ``Message``.

    ``content`` is stripped of surrounding whitespace before validation.
    ``created_at`` defaults to the current UTC time when absent.

    Args:
        value: A :class:`Message` (returned unchanged) or a dict with at least
            ``"role"`` and ``"content"`` keys.

    Returns:
        A validated, immutable :class:`Message`.

    Raises:
        TypeError: If ``value`` is neither a ``Message`` nor a ``dict``.
        ValueError: If ``role`` is not a recognised value, ``content`` is blank,
            or ``metadata`` is not a dict.
    """
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
