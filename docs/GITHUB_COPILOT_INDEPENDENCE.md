# GitHub Copilot independence

Amosclaud does not require an active GitHub Copilot subscription or Copilot cloud-agent account.

## Canonical repository automation

The canonical repository automation is `.github/workflows/amosclaud-bot.yml`. It runs the Amosclaud dispatcher with GitHub Actions' repository-scoped `GITHUB_TOKEN` and, when configured, Amosclaud-owned model/provider credentials.

It does not use:

- `COPILOT_GITHUB_TOKEN`;
- `copilot-setup-steps.yml`;
- the GitHub Copilot CLI;
- Copilot cloud-agent delegation;
- a Copilot subscription for normal bot execution.

## Removed legacy surfaces

The repository no longer includes:

- `.github/copilot-instructions.md`;
- `.github/workflows/issue-bot.yml`;
- `scripts/issue_bot.py`.

The removed issue assistant was a separate legacy Anthropic workflow. Removing it prevents duplicate issue responders and leaves `@amosclaud` and `@amosclaud-bot` under the canonical Amosclaud dispatcher only.

## Compatibility naming

Some application modules may still use the historical word `copilot` as an internal Amosclaud profile or API compatibility name. Those modules execute Amosclaud's own pipeline and do not contact, authenticate to, or depend on GitHub Copilot. They can be renamed through a separately versioned API migration without blocking repository automation.

## Regression protection

`tests/test_amosclaud_command_ownership.py` fails if a workflow reintroduces Copilot setup jobs, Copilot tokens, the Copilot CLI, or Copilot agent actions.
