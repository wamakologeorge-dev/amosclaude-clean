import asyncio

from amosclaud_agent_sdk.errors import ToolPermissionError
from amosclaud_agent_sdk.options import AmosclaudAgentOptions, HookMatcher
from amosclaud_agent_sdk.tools import create_tool_server, tool


@tool("greet", "Greet a user", {"name": "string"})
async def greet(arguments):
    return {"content": [{"type": "text", "text": f"Hello {arguments['name']}"}]}


def test_in_process_tool_and_hook_permission():
    server = create_tool_server("tests", [greet])
    allowed = AmosclaudAgentOptions(allowed_tools={"greet"})
    assert asyncio.run(server.invoke("greet", {"name": "George"}, allowed))["content"][0]["text"] == "Hello George"

    async def deny(_event):
        return {"permission": "deny", "reason": "blocked in test"}

    denied = AmosclaudAgentOptions(
        allowed_tools={"greet"},
        hooks={"PreToolUse": [HookMatcher("greet", (deny,))]},
    )
    try:
        asyncio.run(server.invoke("greet", {"name": "George"}, denied))
    except ToolPermissionError as error:
        assert "blocked in test" in str(error)
    else:
        raise AssertionError("denied tool was executed")
