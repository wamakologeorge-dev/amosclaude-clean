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
