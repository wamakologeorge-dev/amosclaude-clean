# Amosclaud Autonomous for VS Code

Use Amosclaud as a repository-aware assistant and self terminal in desktop VS
Code, GitHub Codespaces, `vscode.dev`, and `insiders.vscode.dev`.

## Surfaces

- Type `@amosclaud` in VS Code Chat.
- Open the Amosclaud activity-bar view for an independent chat panel.
- Open **Terminal: Select Default Profile** and choose **Amosclaud Self
  Terminal**.
- Run **Amosclaud: Open Self Terminal** from the Command Palette.
- Use **Amosclaud: Plan Current Task** or **Amosclaud: Run Current Task**.
- Select the **Amosclaud Autonomous** custom agent when the workspace MCP server
  is enabled.

## Self terminal

The self terminal is a VS Code Pseudoterminal connected to the managed Amosclaud
runtime over a short-lived, single-use WebSocket ticket. It is not the local
PowerShell terminal shown by `vscode.dev` when no compute environment is
attached.

When a terminal opens:

1. The extension reads the current user's Autonomous key from VS Code Secret
   Storage.
2. Amosclaud lists only repositories owned by that account.
3. The user selects a repository.
4. The server starts that repository's managed workspace.
5. A one-time ticket opens a Bash, `sh`, or Python terminal inside the selected
   repository.

Each account has independent authentication, repository access checks, runtime
identity, home directory, and active-session limits. A ticket is bound to one
user, one repository, one terminal id, and one profile; it cannot be reused.
Managed same-service terminals remain owner-only. Team developers can use the
separate isolated workspace runtime when organization collaboration is enabled.

Configure the default terminal profile with `amosclaud.terminalProfile`:

- `bash` — normal Amosclaud development shell;
- `sh` — minimal POSIX shell;
- `python` — interactive Python session.

## Chat commands

- `@amosclaud /plan` prepares a governed plan.
- `@amosclaud /run` starts authorized Autonomous work.
- `@amosclaud /fix` routes a verified repair through Amosclaud Fixer.
- `@amosclaud /build` routes build and test work through Amosclaud Action.
- `@amosclaud /deploy` prepares governed deployment work.
- `@amosclaud /security` prepares a security review.
- `@amosclaud /agents` lists internal capabilities.
- `@amosclaud /status` checks the platform.

The extension stores the bearer token in VS Code Secret Storage. It sends only
bounded editor context and explicitly selected text. Repository writes,
protected branches, merges, deployments, and secret operations remain subject
to Amosclaud authorization and verification.

## Installation and configuration

The default platform URL is `https://www.amosclaud.com`. Configure a different
HTTPS installation with the `amosclaud.baseUrl` setting. Exact localhost HTTP
URLs are accepted for development.

Every user must create and store their own Amosclaud Autonomous key. Do not share
one user's key between accounts, workspaces, screenshots, issues, or repository
files.

For a test installation:

1. Download the `amosclaud-autonomous-vsix` artifact from the successful
   **Amosclaud VS Code Extension** workflow.
2. In desktop VS Code or a compatible remote environment, run **Extensions:
   Install from VSIX**.
3. Run **Amosclaud: Configure Autonomous Token** and store that user's personal
   key.
4. Run **Amosclaud: Open Self Terminal**.
5. Select a repository owned by that Amosclaud account.

Browser-only VS Code should use the published Marketplace version when the
`amosclaud` publisher release is available.

## Local development

1. Open this folder in VS Code.
2. Run `npm run check`, `npm test`, and `npm run build`.
3. Press `F5` for the desktop Extension Development Host, or use a VS Code web
   extension development host for browser testing.
4. Run **Amosclaud: Configure Autonomous Token**.
5. Run **Amosclaud: Open Self Terminal** and select an owned repository.
