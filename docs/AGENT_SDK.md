# Amosclaud Agent SDK

The SDK connects Python applications and terminals to the governed Autonomous
runtime at `https://www.amosclaud.com`.

```bash
pip install amosclaud
export AMOSCLAUD_API_KEY="amos_aut_..."
amosclaud-agent status
amosclaud-agent run "Inspect this repository" --mode build --wait
```

```python
from amosclaud_agent_sdk import AmosclaudAgentClient

agent = AmosclaudAgentClient(api_key="amos_aut_...")
result = agent.run_and_wait("Run the checks and report the first blocker", mode="build")
print(result)
```

External programs and remote runners require an Autonomous API key. The signed-in
administrator dashboard uses its secure `amos_session` cookie and does not require
an API key. Never place either credential in source control.

## Build the package

```bash
python -m pip install build twine
python scripts/build_wheel.py --clean
```

The build produces a wheel and source distribution, validates both with Twine,
and restores version files after temporary release builds. It never downloads or
runs a third-party installer.

## Async query

```python
from amosclaud_agent_sdk import AmosclaudAgentOptions, query

options = AmosclaudAgentOptions(max_turns=4, cwd=".")
async for message in query("Inspect this project", options=options):
    print(message.type, message.content)
```

## In-process tools and permission hooks

```python
from amosclaud_agent_sdk import AmosclaudAgentOptions, HookMatcher
from amosclaud_agent_sdk import AmosclaudSDKClient, create_tool_server, tool

@tool("greet", "Greet a user", {"name": "string"})
async def greet(arguments):
    return {"content": [{"type": "text", "text": f"Hello {arguments['name']}"}]}

async def protect_tools(event):
    if event["tool_name"] == "dangerous-tool":
        return {"permission": "deny", "reason": "blocked by application policy"}
    return {"permission": "allow"}

server = create_tool_server("my-tools", [greet])
options = AmosclaudAgentOptions(
    allowed_tools={"greet"},
    hooks={"PreToolUse": [HookMatcher("*", (protect_tools,))]},
)

async with AmosclaudSDKClient(options=options) as client:
    await client.send("Help me greet George")
    async for message in client.receive():
        print(message)
```

Tools run in the developer's Python process. They are never automatically
published to Amosclaud.com, and disallowed or non-allowlisted tools fail closed.

## Release contract

`scripts/build_wheel.py --version X.Y.Z` sets a temporary package build version.
The repository-owned `amosclaud-agent` command is included through normal Python
wheel metadata. The build never downloads a third-party CLI or installer.

The SDK uses the repository's Amosclaud proprietary/commercial license files.
It does not inherit Anthropic's commercial terms because no Anthropic code or
Claude Code binary is bundled.
