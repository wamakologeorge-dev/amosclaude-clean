# Amosclaud Autonomous for VS Code

This extension is a thin client for the existing Amosclaud Copilot and governed Autonomous pipeline. It does not create a second autonomous runtime.

## Capabilities

- open a persistent Amosclaud chat view;
- preview routing with **Plan safely**;
- authorize governed repository work with **Run authorized work**;
- optionally prefer an internal capability role such as Fixer, Action, Security, Clean, Codex, or Autonomous;
- include only the active repository, branch, relative file path, language, and selected text;
- store the bearer token in VS Code Secret Storage.

The extension never sends an entire file automatically. It rejects `.env`, private-key, certificate, credential, and `secrets/` paths.

## Local development

1. Open this folder in VS Code.
2. Run `npm test`.
3. Press `F5` to launch an Extension Development Host.
4. Configure `amosclaud.baseUrl` when using a local server.
5. Run **Amosclaud: Configure Autonomous Token**.

Production requests default to `https://www.amosclaud.com/api/v1/copilot`.

## Commands

- `Amosclaud: Configure Autonomous Token`
- `Amosclaud: Plan Current Task`
- `Amosclaud: Run Current Task`

Plan requests do not start repository execution. Run requests enter the same approval, branch, verification, and Results controls used by Amosclaud Autonomous.
