# Amosclaud Autonomous for VS Code

Use Amosclaud as a repository-aware assistant in desktop VS Code, GitHub
Codespaces, `vscode.dev`, and `insiders.vscode.dev`.

## Surfaces

- Type `@amosclaud` in VS Code Chat.
- Open the Amosclaud activity-bar view for an independent chat panel.
- Use `Amosclaud: Plan Current Task` or `Amosclaud: Run Current Task` from the
  Command Palette.
- Select the **Amosclaud Autonomous** custom agent when the workspace MCP server
  is enabled.

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

## Configuration

The default platform URL is `https://www.amosclaud.com`. Configure a different
HTTPS installation with the `amosclaud.baseUrl` setting. Exact localhost HTTP
URLs are accepted for development.

## Local development

1. Open this folder in VS Code.
2. Run `npm run check` and `npm test`.
3. Press `F5` for the desktop Extension Development Host, or use a VS Code web
   extension development host for browser testing.
4. Run **Amosclaud: Configure Autonomous Token**.
