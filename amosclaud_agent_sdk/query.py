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
    type: Literal["assistant", "status", "result"]
    content: str
    data: dict[str, Any]


async def query(
    prompt: str,
    *,
    options: AmosclaudAgentOptions | None = None,
    client: AmosclaudAgentClient | None = None,
) -> AsyncIterator[QueryMessage]:
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
