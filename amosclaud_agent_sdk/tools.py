"""In-process, typed tools with explicit permission hooks."""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .errors import ToolPermissionError
from .options import AmosclaudAgentOptions

ToolHandler = Callable[[dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler


def tool(name: str, description: str, input_schema: dict[str, Any]):
    """Decorate an async or synchronous Python function as an Amosclaud tool."""

    def decorate(handler: ToolHandler) -> Tool:
        return Tool(name=name, description=description, input_schema=input_schema, handler=handler)

    return decorate


class ToolServer:
    def __init__(self, name: str, version: str, tools: list[Tool]) -> None:
        self.name, self.version = name, version
        self.tools = {item.name: item for item in tools}
        if len(self.tools) != len(tools):
            raise ValueError("tool names must be unique")

    async def invoke(
        self,
        name: str,
        arguments: dict[str, Any],
        options: AmosclaudAgentOptions,
    ) -> dict[str, Any]:
        if name not in self.tools:
            raise KeyError(f"unknown tool: {name}")
        if name in options.disallowed_tools:
            raise ToolPermissionError(f"tool is disallowed: {name}")
        if options.allowed_tools and name not in options.allowed_tools:
            raise ToolPermissionError(f"tool is not allowlisted: {name}")
        event = {"event": "PreToolUse", "tool_name": name, "tool_input": arguments}
        for matcher in options.hooks.get("PreToolUse", []):
            if matcher.matcher not in {"*", name}:
                continue
            for hook_handler in matcher.hooks:
                decision = hook_handler(event)
                if inspect.isawaitable(decision):
                    decision = await decision
                if decision.get("permission") == "deny":
                    raise ToolPermissionError(str(decision.get("reason") or "tool denied by hook"))
        result = self.tools[name].handler(arguments)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, dict):
            raise TypeError("tool handlers must return a dictionary")
        return result


def create_tool_server(name: str, tools: list[Tool], version: str = "1.0.0") -> ToolServer:
    return ToolServer(name=name, version=version, tools=tools)
