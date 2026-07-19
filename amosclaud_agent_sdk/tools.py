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
    """A named, typed callable registered with a :class:`ToolServer`.

    Construct via the :func:`tool` decorator rather than directly.

    Attributes:
        name: Unique identifier used to route invocations.
        description: Human-readable summary forwarded to the agent as tool metadata.
        input_schema: JSON Schema dict describing the expected ``arguments`` structure.
        handler: Sync or async callable that receives ``arguments`` and returns a dict.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler


def tool(name: str, description: str, input_schema: dict[str, Any]):
    """Decorate an async or synchronous Python function as an Amosclaud tool.

    Args:
        name: Unique tool name used for routing. Must not conflict with other
            tools registered on the same :class:`ToolServer`.
        description: Shown to the agent when it selects which tool to invoke.
        input_schema: JSON Schema object describing the ``arguments`` dict the
            handler will receive.

    Returns:
        A decorator that wraps the function in a :class:`Tool` instance.

    Example::

        @tool("read_file", "Read a text file from disk", {"type": "object", ...})
        async def read_file(arguments: dict) -> dict:
            ...
    """

    def decorate(handler: ToolHandler) -> Tool:
        return Tool(name=name, description=description, input_schema=input_schema, handler=handler)

    return decorate


class ToolServer:
    """Registry that routes agent tool invocations to local Python handlers.

    Enforces the tool allow/disallow lists from :class:`AmosclaudAgentOptions`
    and runs any ``PreToolUse`` hooks before executing the handler.
    """

    def __init__(self, name: str, version: str, tools: list[Tool]) -> None:
        """
        Args:
            name: Descriptive server name (informational only).
            version: SemVer string for this tool set (informational only).
            tools: Tools to register. Names must be globally unique within this server.

        Raises:
            ValueError: If two tools share the same ``name``.
        """
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
        """Execute a registered tool after checking permissions and running hooks.

        Permission evaluation order:
        1. ``disallowed_tools`` from ``options`` — always blocks.
        2. ``allowed_tools`` from ``options`` — blocks when non-empty and ``name`` is absent.
        3. ``PreToolUse`` hooks — any hook returning ``{"permission": "deny"}`` blocks.

        Args:
            name: Tool name as registered with this server.
            arguments: Input dict passed to the handler unchanged.
            options: Agent options that carry the allow/disallow lists and hooks.

        Returns:
            The dict returned by the handler.

        Raises:
            KeyError: If ``name`` is not registered.
            ToolPermissionError: If a policy or hook denies the invocation.
            TypeError: If the handler returns a non-dict value.
        """
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
    """Convenience constructor for a :class:`ToolServer`.

    Args:
        name: Descriptive server name.
        tools: Tools to register.
        version: Version string; defaults to ``"1.0.0"``.

    Returns:
        A configured :class:`ToolServer` with all tools registered.
    """
    return ToolServer(name=name, version=version, tools=tools)
