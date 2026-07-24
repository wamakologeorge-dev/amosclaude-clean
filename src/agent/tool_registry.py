"""Tool registration and execution for the main Autonomous ReAct loop."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .observations import Observation

ToolHandler = Callable[[dict[str, Any]], Observation]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    handler: ToolHandler
    description: str = ""
    writes: bool = False


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        name = definition.name.strip()
        if not name:
            raise ValueError("tool name cannot be empty")
        if name in self._tools:
            raise ValueError(f"tool is already registered: {name}")
        self._tools[name] = definition

    def names(self) -> frozenset[str]:
        return frozenset(self._tools)

    def write_tools(self) -> frozenset[str]:
        return frozenset(
            name for name, definition in self._tools.items() if definition.writes
        )

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "name": definition.name,
                "description": definition.description,
                "writes": definition.writes,
            }
            for definition in self._tools.values()
        ]

    def execute(self, name: str, arguments: dict[str, Any]) -> Observation:
        if name not in self._tools:
            return Observation(
                tool=name,
                success=False,
                summary=f"unknown tool: {name}",
            )
        try:
            observation = self._tools[name].handler(dict(arguments))
        except Exception as exc:
            return Observation(
                tool=name,
                success=False,
                summary=f"{type(exc).__name__}: {exc}",
            )
        if observation.tool != name:
            return Observation(
                tool=name,
                success=False,
                summary="tool returned an observation with a mismatched name",
            )
        return observation
