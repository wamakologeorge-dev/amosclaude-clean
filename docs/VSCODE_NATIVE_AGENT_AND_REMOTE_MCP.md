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

Remote MCP requests require an Amosclaud bearer credential. Configure:

```text
AMOSCLAUD_AUTONOMOUS_KEY=<protected Autonomous API key>
AMOSCLAUD_MCP_ACCESS_KEY=<optional separate remote MCP key>
AMOSCLAUD_API_URL=https://amosclauds.com
```

When `AMOSCLAUD_MCP_ACCESS_KEY` is blank, the MCP endpoint accepts the configured
Autonomous key. Never commit either key. Scoped Amosclaud authority credentials
can additionally limit native repository access to `repository:read` and
`repository:write`.

The repository includes `.vscode/mcp.json`, which asks each VS Code user for the
key through a protected input rather than storing it in the repository.

The same remote MCP server is also the first-party connection point for other
authorized MCP clients. See `docs/CHATGPT_AMOSCLAUD_MCP.md` for the direct
ChatGPT/MCP architecture and the physical Amosclaud computer path.

## Native Amosclaud repository tools

The MCP server now exposes the native Amosclaud repository provider instead of
requiring an MCP client to hold a GitHub token. Authorized clients can list
repositories, read the tree and files, inspect branches and commits, create
repositories and branches, and commit file changes through Amosclaud.

External repository providers remain optional Amosclaud integrations behind the
control plane. Their credentials are not part of the MCP client contract.

## Multi-user self terminal

The self terminal is a VS Code Pseudoterminal connected to Amosclaud over a
short-lived WebSocket ticket. It works in browser VS Code without requiring a
local PowerShell process or a Codespace merely to display the Amosclaud shell.

The sequence is:

1. VS Code reads that user's Autonomous key from Secret Storage.
2. `GET /api/v1/vscode-terminal/repositories` returns repositories the
   authenticated account can inspect or develop.
3. The user chooses a repository.
4. `POST /api/v1/vscode-terminal/repositories/{id}/start` starts its isolated
   Docker workspace, using a read-only mount for viewers.
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

Tickets are removed on first use. The server rechecks repository access when the
WebSocket opens. Isolated terminals run with a non-root identity, private home
directories, scrubbed environments, repository-scoped working directories,
resource limits, and per-user active-session limits. Viewer sessions cannot
commit or push; developer and owner sessions may use the governed repository
actions.

The available profiles are:

- `bash`
- `sh`
- `python`

Managed same-service terminals remain restricted to developers and owners
because they run in the public service fallback. Repository viewers need the
separate isolated runtime for read-only terminal access.

## Opening the terminal

After installing the extension and configuring a personal Autonomous key:

1. Open the Command Palette.
2. Run **Amosclaud: Open Self Terminal**; or
3. Open **Terminal: Select Default Profile** and select **Amosclaud Self
   Terminal**.
4. Choose one of the repositories available to the current account.

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

The production command runs:

```text
uvicorn amoscloud_ai.combined_app:app --host 0.0.0.0 --port ${PORT:-8000}
```

The deployment target may be an Amosclaud-managed host, a physical Amosclaud
computer, or a temporary external compute provider. `/mcp/` and the terminal
transport are Amosclaud services and should not depend on a particular provider
being the permanent control plane.

After deployment, verify `/health`, the authenticated MCP connection, repository
read/write scopes, and terminal isolation before reporting the deployment as
healthy. Browser users must also install the built VSIX or Marketplace release
of the extension.

## GitHub integration boundary

When GitHub is connected, Amosclaud performs approved GitHub operations through
its GitHub App, repository-scoped Actions, webhooks, issues, branches, pull
requests, checks, and protected Autonomous pipeline. GitHub is an optional
provider integration rather than the MCP identity or control plane. Native
Amosclaud repositories can be accessed through MCP without giving the client a
GitHub credential.
