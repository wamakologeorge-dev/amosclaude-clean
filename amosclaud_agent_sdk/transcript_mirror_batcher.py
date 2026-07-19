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
    """Split a sequence of messages into bounded batches for mirroring or remote sync.

    A new batch is started whenever adding the next message would exceed either
    ``max_messages`` or ``max_chars``. Each message is counted by its raw
    ``content`` length (not the serialized JSON length).

    Args:
        messages: Source messages, consumed lazily.
        max_messages: Maximum number of messages per batch. Must be >= 1.
        max_chars: Maximum cumulative ``content`` character count per batch. Must be >= 1.

    Yields:
        Non-empty lists of message dicts (as returned by
        :meth:`~amosclaud_agent_sdk.message_parser.Message.to_dict`).

    Raises:
        ValueError: If either limit is less than 1.
    """
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
