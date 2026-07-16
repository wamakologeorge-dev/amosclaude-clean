"""Typed configuration for queries, tools, hooks, and workspace scope."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

PermissionMode = Literal["ask", "allow-read", "accept-edits"]
Hook = Callable[[dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class HookMatcher:
    matcher: str
    hooks: tuple[Hook, ...]


@dataclass(slots=True)
class AmosclaudAgentOptions:
    system_prompt: str | None = None
    max_turns: int = 8
    cwd: str | Path | None = None
    allowed_tools: set[str] = field(default_factory=set)
    disallowed_tools: set[str] = field(default_factory=set)
    permission_mode: PermissionMode = "ask"
    hooks: dict[str, list[HookMatcher]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 1 <= self.max_turns <= 100:
            raise ValueError("max_turns must be between 1 and 100")
        if self.allowed_tools & self.disallowed_tools:
            raise ValueError("a tool cannot be both allowed and disallowed")
        if self.cwd is not None:
            path = Path(self.cwd).expanduser().resolve()
            if not path.is_dir():
                raise ValueError("cwd must be an existing directory")
            self.cwd = path
