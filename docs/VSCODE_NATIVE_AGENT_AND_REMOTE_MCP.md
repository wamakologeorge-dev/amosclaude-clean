# Amosclaud native VS Code agent, remote MCP, and self terminal

Amosclaud can operate in desktop VS Code, Codespaces, `vscode.dev`,
`insiders.vscode.dev`, and `github.dev` through three connected surfaces:

- the `@amosclaud` Chat participant;
- the protected remote MCP endpoint at `/mcp/`;
- the **Amosclaud Self Terminal** terminal profile.

These surfaces delegate to the existing governed Amosclaud platform. They do not
create a second orchestration root or bypass repository permissions, approvals,
branch protection, verification, or Results reporting.

## VS Code chat

The extension registers `@amosclaud` with these commands:

- `/plan`
- `/run`
- `/fix`
- `/build`
- `/deploy`
- `/security`
- `/agents`
- `/status`

The independent Amosclaud activity-bar panel remains available for users who do
not want to use the shared VS Code Chat interface.

## Remote MCP

The combined production ASGI application serves the existing platform at `/`
and the first-party Streamable HTTP MCP server at `/mcp/`.

Remote MCP requests require a bearer key. Configure:

```text
AMOSCLAUD_AUTONOMOUS_KEY=<protected Autonomous API key>
AMOSCLAUD_MCP_ACCESS_KEY=<optional separate remote MCP key>
AMOSCLAUD_API_URL=https://www.amosclaud.com
```

When `AMOSCLAUD_MCP_ACCESS_KEY` is blank, the MCP endpoint accepts the configured
Autonomous key. Never commit either key.

The repository includes `.vscode/mcp.json`, which asks each VS Code user for the
key through a protected input rather than storing it in the repository.

## Multi-user self terminal

The self terminal is a VS Code Pseudoterminal connected to Amosclaud over a
short-lived WebSocket ticket. It works in browser VS Code without requiring a
local PowerShell process or a Codespace merely to display the Amosclaud shell.

The sequence is:

1. VS Code reads that user's Autonomous key from Secret Storage.
2. `GET /api/v1/vscode-terminal/repositories` returns only repositories owned by
   the authenticated account.
3. The user chooses a repository.
4. `POST /api/v1/vscode-terminal/repositories/{id}/start` starts its managed
   workspace.
5. `POST /api/v1/vscode-terminal/repositories/{id}/ticket` creates a 120-second,
   single-use ticket.
6. VS Code connects to the returned `wss://` address and streams the repository
   PTY into the integrated terminal.

Every ticket is bound to:

- one Amosclaud user;
- one repository;
- one workspace;
- one terminal identifier;
- one runtime profile;
- one expiration time.

Tickets are removed on first use. The server rechecks repository ownership when
the WebSocket opens. Managed terminals run with per-user runtime identities,
private home directories, scrubbed environments, repository-scoped working
directories, and per-user active-session limits.

The available profiles are:

- `bash`
- `sh`
- `python`

Managed same-service terminals remain owner-only because they run in the public
service fallback. Organization developers should use the separate isolated
workspace runtime when collaborative terminal access is enabled.

## Opening the terminal

After installing the extension and configuring a personal Autonomous key:

1. Open the Command Palette.
2. Run **Amosclaud: Open Self Terminal**; or
3. Open **Terminal: Select Default Profile** and select **Amosclaud Self
   Terminal**.
4. Choose one of the repositories owned by the current account.

## Packaging

The extension package lives in `clients/vscode-amosclaud`.

```bash
cd clients/vscode-amosclaud
npm run check
npm test
npm run build
npx --yes @vscode/vsce package --no-dependencies
```

The `Amosclaud VS Code Extension` workflow performs the same checks, builds the
browser bundle, packages a VSIX, and uploads it as a workflow artifact.
Marketplace publication remains a release operation requiring the Amosclaud
publisher account and its protected publishing credential.

## Deployment

The production Docker command runs:

```text
uvicorn amoscloud_ai.combined_app:app --host 0.0.0.0 --port ${PORT:-8000}
```

After merge, Railway must deploy the new image before `/mcp/` and the VS Code
terminal transport become available. Browser users must also install the built
VSIX or the Marketplace release of the extension.

## GitHub integration boundary

Amosclaud performs approved GitHub operations through its GitHub App,
repository-scoped Actions, webhooks, issues, branches, pull requests, checks,
and protected Autonomous pipeline. GitHub's own chat interface remains a
separate product surface. Amosclaud uses only the permissions granted by the
repository owner.
