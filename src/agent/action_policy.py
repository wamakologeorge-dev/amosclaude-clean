"""Authorization and safety policy for ReAct tool actions."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ActionPolicy:
    """Allow reads by default and require explicit permission for mutations."""

    authorized_writes: bool = False
    allowed_tools: frozenset[str] = field(default_factory=frozenset)
    write_tools: frozenset[str] = field(default_factory=frozenset)

    def authorize(self, tool_name: str) -> tuple[bool, str]:
        if tool_name not in self.allowed_tools:
            return False, f"tool is not registered for this task: {tool_name}"
        if tool_name in self.write_tools and not self.authorized_writes:
            return False, f"write authorization is required for tool: {tool_name}"
        return True, "authorized"
