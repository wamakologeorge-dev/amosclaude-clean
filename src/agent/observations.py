"""Typed evidence produced by governed ReAct actions."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Observation:
    """Evidence returned by one tool action.

    Observations contain results and references, never private reasoning text.
    """

    tool: str
    success: bool
    summary: str
    evidence: tuple[str, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
