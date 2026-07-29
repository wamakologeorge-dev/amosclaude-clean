# Amosclaud Workflow Results Dashboard

[![Amosclaud Autonomous Fixer](https://github.com/wamakologeorge-dev/amosclaude-clean/actions/workflows/amosclaud-fixer.yml/badge.svg)](https://github.com/wamakologeorge-dev/amosclaude-clean/actions/workflows/amosclaud-fixer.yml)

This dashboard is the real results area for Amosclaud Autonomous jobs.

It gives users a Railway-style place to:

- create projects;
- configure repository URL and workspace root path;
- change build, start, test, or verification commands;
- define the output path that should become an artifact;
- add environment variables and encrypted secrets;
- run a workflow and inspect real process logs and exit codes;
- open generated artifact manifests;
- configure and verify custom domains with a DNS TXT record.

## Run it

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8100
```

## VS Code, MCP, and self terminal

See [`docs/VSCODE_NATIVE_AGENT_AND_REMOTE_MCP.md`](docs/VSCODE_NATIVE_AGENT_AND_REMOTE_MCP.md)
for the `@amosclaud` chat participant, remote MCP tools, installable VSIX, and
multi-user Amosclaud Self Terminal.
