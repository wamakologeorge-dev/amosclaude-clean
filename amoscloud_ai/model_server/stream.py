"""Streaming adapters for web and worker consumers."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable, Iterator
import json


@dataclass(frozen=True)
class TokenEvent:
    type: str
    sequence: int
    text: str = ""
    model: str = ""
    finish_reason: str | None = None
    created_at: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["created_at"] = (
            self.created_at or datetime.now(timezone.utc).isoformat()
        )
        return data

    def to_sse(self) -> str:
        payload = json.dumps(self.to_dict(), ensure_ascii=False)
        return f"event: {self.type}\ndata: {payload}\n\n"


def token_events(
    chunks: Iterable[str],
    *,
    model: str = "",
) -> Iterator[TokenEvent]:
    yield TokenEvent(type="start", sequence=0, model=model)
    sequence = 0
    try:
        for sequence, chunk in enumerate(chunks, start=1):
            yield TokenEvent(
                type="token",
                sequence=sequence,
                text=chunk,
                model=model,
            )
    except Exception as exc:
        yield TokenEvent(
            type="error",
            sequence=sequence + 1,
            model=model,
            finish_reason=f"{type(exc).__name__}: {exc}",
        )
        raise
    yield TokenEvent(
        type="complete",
        sequence=sequence + 1,
        model=model,
        finish_reason="stop",
    )


def sse_stream(
    chunks: Iterable[str],
    *,
    model: str = "",
) -> Iterator[str]:
    for event in token_events(chunks, model=model):
        yield event.to_sse()
