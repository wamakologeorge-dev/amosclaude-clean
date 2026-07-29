# Amosclaud native VS Code agent and remote MCP

## Why the earlier integration did not appear

The first IDE companion was merged as source code, but three runtime pieces were
missing:

1. its extension manifest had only a Node.js `main` entry point, so the browser
   extension host used by `vscode.dev`, `insiders.vscode.dev`, and `github.dev`
   ignored it;
2. it contributed a separate webview but did not register a VS Code Chat
   participant, so VS Code Chat had no `@amosclaud` participant to route to;
3. the first-party MCP server used local `stdio` only and the workspace did not
   contain `.vscode/mcp.json`, so browser VS Code could not start or discover
   Amosclaud tools.

## Implemented surfaces

The extension now uses one browser-safe entry point for desktop and web VS Code.
It registers:

- the independent Amosclaud activity-bar chat view;
- the `@amosclaud` VS Code Chat participant;
- `/plan`, `/run`, `/fix`, `/build`, `/deploy`, `/security`, `/agents`, and
  `/status` chat commands;
- Command Palette plan, run, and token commands.

The repository also includes:

- `.vscode/mcp.json`, which configures the remote `amosclaud` MCP server;
- `.github/agents/amosclaud.agent.md`, which exposes one Amosclaud Autonomous
  custom agent using all `amosclaud/*` MCP tools;
- a workflow that tests and packages the extension as a VSIX.

## Remote MCP transport

The production container serves `amoscloud_ai.combined_app:app`.

- `/` is the existing Amosclaud FastAPI platform.
- `/mcp` is the first-party MCP server over stateless Streamable HTTP.
- browser editor origins are allowed by an outer CORS layer.
- every MCP protocol request requires a bearer key.

Configure these Railway variables:

```text
AMOSCLAUD_AUTONOMOUS_KEY=<existing protected Autonomous API key>
AMOSCLAUD_MCP_ACCESS_KEY=<separate optional MCP access key>
AMOSCLAUD_API_URL=https://www.amosclaud.com
```

When `AMOSCLAUD_MCP_ACCESS_KEY` is not set, the remote MCP endpoint accepts the
configured `AMOSCLAUD_AUTONOMOUS_KEY`. A dedicated MCP key is preferred because
it can be rotated independently.

Never commit either value. VS Code prompts for the MCP key from `.vscode/mcp.json`
and stores the value as a protected input. The extension stores its API token in
VS Code Secret Storage.

## Install and publish the extension

The `Amosclaud VS Code Extension` workflow packages:

```text
artifacts/amosclaud-autonomous.vsix
```

Desktop VS Code and Codespaces can install the VSIX for testing. Browser VS Code
loads coded extensions from the Visual Studio Marketplace, so create the
`amosclaud` Marketplace publisher, add a repository secret named `VSCE_PAT`, and
run the workflow manually with **publish** enabled.

After publication, search for **Amosclaud Autonomous** in Extensions and install
it. Then type:

```text
@amosclaud /status
@amosclaud /plan inspect this repository and identify the first verified blocker
@amosclaud /run build and test this project
```

## GitHub integration boundary

Amosclaud performs approved GitHub operations through its GitHub App,
repository-scoped Actions, webhooks, issues, branches, pull requests, checks, and
its protected Autonomous pipeline. GitHub's own chat interface remains a
separate product surface. The supported integration is explicit and auditable:
Amosclaud's chat participant, MCP tools, GitHub App permissions, and workflow
jobs all use the permissions granted by the repository owner.
