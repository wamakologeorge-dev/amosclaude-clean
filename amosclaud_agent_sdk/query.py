"""Async one-shot Amosclaud query interface."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

from .client import AmosclaudAgentClient
from .options import AmosclaudAgentOptions


@dataclass(frozen=True, slots=True)
class QueryMessage:
    """A single event yielded by :func:`query`.

    Attributes:
        type: One of ``"status"`` (in-progress notification), ``"assistant"``
            (the agent's reply text), or ``"result"`` (terminal event carrying
            the full API response).
        content: Human-readable text for this event.
        data: Full raw response dict from the Amosclaud API, or a minimal status
            dict for ``"status"`` events.
    """

    type: Literal["assistant", "status", "result"]
    content: str
    data: dict[str, Any]


async def query(
    prompt: str,
    *,
    options: AmosclaudAgentOptions | None = None,
    client: AmosclaudAgentClient | None = None,
) -> AsyncIterator[QueryMessage]:
    """Submit a one-shot prompt to Amosclaud Autonomous and stream back events.

    Yields exactly three :class:`QueryMessage` objects in order:

    1. ``"status"`` — emitted immediately before the blocking HTTP call.
    2. ``"assistant"`` — the agent's reply extracted from the pipeline result.
    3. ``"result"`` — terminal event containing the same reply and full data dict.

    The HTTP call runs in a thread via :func:`asyncio.to_thread` so the event
    loop is not blocked during the polling wait.

    Args:
        prompt: The task or question to send to the agent.
        options: Configuration for the query (system prompt, tool lists, etc.).
            Defaults to :class:`~amosclaud_agent_sdk.options.AmosclaudAgentOptions`
            with its default values.
        client: HTTP client. Defaults to a new
            :class:`~amosclaud_agent_sdk.client.AmosclaudAgentClient`.

    Yields:
        :class:`QueryMessage` instances describing query progress and the final result.

    Raises:
        AmosclaudAgentError: Propagated from :meth:`~AmosclaudAgentClient.run_and_wait`
            on network or API failure.
    """
    configured = options or AmosclaudAgentOptions()
    api = client or AmosclaudAgentClient()
    metadata = dict(configured.metadata)
    metadata.update(
        {
            "system_prompt": configured.system_prompt,
            "max_turns": configured.max_turns,
            "cwd": str(configured.cwd) if configured.cwd else None,
            "allowed_tools": sorted(configured.allowed_tools),
            "disallowed_tools": sorted(configured.disallowed_tools),
            "permission_mode": configured.permission_mode,
            "source": "amosclaud-agent-sdk-query",
        }
    )
    yield QueryMessage("status", "Requesting Amosclaud Autonomous", {"status": "starting"})
    result = await asyncio.to_thread(api.run_and_wait, prompt, mode="build", metadata=metadata)
    reply = str(result.get("reply") or result.get("message") or "Task completed")
    yield QueryMessage("assistant", reply, result)
    yield QueryMessage("result", reply, result)
