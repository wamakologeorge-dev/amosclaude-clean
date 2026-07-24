# Amosclaud Autonomous Codex Connector

This connector exposes the Amosclaud Autonomous Runtime as a small MCP tool server. It keeps the autonomous runtime primary and does not enable the optional engineering agent.

## Tools

- `amosclaud_health`
- `amosclaud_run`
- `amosclaud_pipeline`

## Environment

```bash
AMOSCLAUD_BASE_URL=https://amosclaud.com
AMOSCLAUD_API_KEY=replace-with-your-amosclaud-key
```

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r connectors/codex/requirements.txt
python connectors/codex/server.py
```

The connector uses stdio transport. Configure the MCP client to launch `python connectors/codex/server.py` with the two environment variables above.

## Safety

The connector does not expose an unrestricted shell. It only calls explicit Amosclaud API routes. Autonomous runs always send `use_agent: false` so Amosclaud Autonomous remains in control.
