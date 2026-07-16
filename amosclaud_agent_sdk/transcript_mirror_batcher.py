"""Bounded transcript batches for mirrors, logs, and remote synchronization."""
from __future__ import annotations

from collections.abc import Iterable, Iterator

from .message_parser import Message


def transcript_batches(
    messages: Iterable[Message],
    *,
    max_messages: int = 25,
    max_chars: int = 32_000,
) -> Iterator[list[dict]]:
    if max_messages < 1 or max_chars < 1:
        raise ValueError("batch limits must be positive")
    batch: list[dict] = []
    size = 0
    for message in messages:
        encoded = message.to_dict()
        length = len(message.content)
        if batch and (len(batch) >= max_messages or size + length > max_chars):
            yield batch
            batch, size = [], 0
        batch.append(encoded)
        size += length
    if batch:
        yield batch
