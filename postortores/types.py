"""Typed records used by the Amosclaud Postortores data system."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DataRecord:
    namespace: str
    key: str
    value: dict[str, Any]
    version: int = 1
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EventRecord:
    stream: str
    event_type: str
    payload: dict[str, Any]
    actor: str = "system"


@dataclass(slots=True)
class MemoryRecord:
    owner: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None


@dataclass(slots=True)
class EvidenceRecord:
    subject: str
    claim: str
    status: str
    proof: dict[str, Any] = field(default_factory=dict)
