# Amosclaud IDE Companion

Status: **portable editor adapter for Amosclaud Autonomous**

The IDE Companion makes the existing governed Amosclaud Autonomous workflow available in VS Code, Xcode, terminals, and other local editors. It is not a second agent runtime. Every plan and execution request delegates to the existing `/api/v1/copilot` adapter and the canonical Autonomous pipeline.

## Components

```text
Developer
   |
   +-- VS Code chat panel
   +-- Xcode Swift companion
   +-- amosclaud-ide CLI
              |
              v
      /api/v1/copilot/plan
      /api/v1/copilot/run
              |
              v
      Amosclaud Autonomous
              |
              v
       Repository + Results
```

- `amoscloud_ai/ide_client.py` provides an installable, dependency-free CLI.
- `clients/vscode-amosclaud` provides a VS Code chat view and commands.
- `clients/xcode-amosclaud` provides a native Swift executable and Xcode behavior launcher.

## One identity, internal capability routing

The editor shows one user-facing identity: **Amosclaud Autonomous**. A developer may optionally prefer an internal capability role for routing:

- Codex for implementation and code explanation;
- Fixer for verified repairs;
- Action for tests and GitHub Actions;
- Security for authentication, permissions, secrets, and risk review;
- Clean for lint, formatting, and maintainability;
- Autonomous for end-to-end repository work;
- AI for explanation and requirements.

These roles do not bypass the canonical kernel, approval rules, branch protection, verification, or Results reporting.

## Context boundary

Clients may send only:

- selected repository name;
- current branch;
- repository-relative active file path;
- editor language identifier;
- explicitly selected text, capped at 16,000 characters;
- the developer task and optional routing preference.

Clients do not automatically send whole files or workspace trees. They reject absolute paths, `..` traversal, `.env` files, private keys, certificate files, credential files, and paths inside `secrets/`.

## Authentication

- The Python CLI reads `AMOSCLAUD_AUTONOMOUS_KEY`, `AMOSCLAUD_TOKEN`, or `AMOSCLAUD_SESSION_COOKIE`.
- The VS Code extension stores its token in VS Code Secret Storage.
- The Xcode companion reads environment variables or macOS Keychain service `amosclaud-autonomous`.

Tokens must never be committed, placed in editor settings, included in chat context, or printed in Results.

## Plan and execution modes

`plan` previews deterministic routing and the exact bounded Autonomous handoff. It does not start repository execution.

`run` is an explicit authorization to enter the existing governed workflow. It still cannot write directly to protected branches, merge, deploy, expose secrets, or perform another protected action without the required approval.

## CLI examples

```bash
amosclaud-ide doctor
amosclaud-ide agents
amosclaud-ide plan "Explain this module" \
  --repository wamakologeorge-dev/amosclaude-clean \
  --file amoscloud_ai/copilot.py \
  --language python
amosclaud-ide run "Fix and verify the failing test" --agent fixer
amosclaud-ide chat
```

## Verification

The Python tests cover HTTPS enforcement, path containment, sensitive-file blocking, bounded selection context, payload construction, and empty-task rejection.

The VS Code Node tests cover the equivalent client-side boundaries. The Xcode package is designed for `swift build` and `swift run` on macOS 13 or later.

## Known limitations

- The first Xcode release is a native Swift command-line companion and behavior launcher, not an App Store Source Editor Extension.
- The VS Code release returns structured plan and execution JSON; richer diff and pipeline timeline rendering can be added without changing the backend contract.
- Clients require a reachable Amosclaud backend and a valid credential for plan and run operations.
