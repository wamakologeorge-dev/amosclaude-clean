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
    """Associates one or more hook callables with a tool name pattern.

    Attributes:
        matcher: Tool name to match, or ``"*"`` to match every tool.
        hooks: Callables invoked before the matched tool executes. Each receives
            a ``{"event", "tool_name", "tool_input"}`` dict and must return a dict.
            Returning ``{"permission": "deny", "reason": "..."}`` blocks execution.
    """

    matcher: str
    hooks: tuple[Hook, ...]


@dataclass(slots=True)
class AmosclaudAgentOptions:
    """Configuration for a single Amosclaud query or multi-turn session.

    Attributes:
        system_prompt: Optional instruction prepended to every query context.
        max_turns: Maximum agent turns before the pipeline is halted. Must be 1–100.
        cwd: Working directory constraint for the agent. Resolved and validated
            at construction time; ``None`` applies no constraint.
        allowed_tools: When non-empty, only tools in this set may be invoked.
        disallowed_tools: Tools in this set are unconditionally blocked.
        permission_mode: Controls how the agent handles ambiguous file edits.
            ``"ask"`` requires approval, ``"allow-read"`` permits reads freely,
            ``"accept-edits"`` permits all edits.
        hooks: ``PreToolUse`` hooks keyed by event name. Each value is a list of
            :class:`HookMatcher` instances evaluated in order.
        metadata: Arbitrary context forwarded to the Amosclaud pipeline.

    Raises:
        ValueError: On construction if ``max_turns`` is out of range, a tool
            appears in both ``allowed_tools`` and ``disallowed_tools``, or
            ``cwd`` is not an existing directory.
    """

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
