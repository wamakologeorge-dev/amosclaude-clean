# Amosclaud Developer Fast Path

Amosclaud provides a local, zero-account command that gives a developer useful repository evidence before any cloud onboarding, API key, model request, or dashboard visit.

## Ten-second local value

After installing the repository package, run:

```bash
amosclaud-quick . --objective "Find the cause of the login failure"
```

The command performs two deterministic operations:

1. It maps the repository and selects the smallest relevant code context, capped at 50 lines by default.
2. It validates supported Python, JSON, YAML, and TOML files and detects unresolved merge markers.

It does not contact `www.amosclaud.com`, invoke a language model, require an account, or require an API key.

Machine-readable output is available for scripts and CI:

```bash
amosclaud-quick . \
  --objective "Inspect the authentication callback" \
  --json \
  --output .amosclaud/quickcheck.json
```

A non-zero exit status means a deterministic guardrail failed.

## Context compression

The context mapper scores file paths and source lines against the engineering objective. It automatically excludes dependency, cache, generated, and build directories including:

- `.git`
- `node_modules`
- `.venv` and `venv`
- `dist` and `build`
- `.next`
- `target`
- `vendor`

The default output contains at most eight files and 50 source lines. Every returned line includes its original file path and line number, making the result suitable for an AI prompt, code-review summary, or autonomous repair plan.

## Sensitive-data boundary

The local mapper never reads common sensitive files, including:

- `.env` and `.env.*`
- private keys and certificate bundles
- credential and secret files
- files inside `secrets` directories

Skipped sensitive paths are reported by name without exposing their contents. A later repair or collection action must use the normal Amosclaud human-approval path before accessing or modifying sensitive material.

## Deterministic guardrails

The first guardrail set is intentionally model-independent:

- Python abstract-syntax-tree parsing
- JSON parsing
- YAML safe parsing
- TOML parsing
- unresolved merge-marker detection

These checks are fast enough for local use and produce stable JSON evidence. Full test, type-check, security-scan, and build pipelines remain authoritative before Amosclaud pushes a branch or opens a pull request.

## Relationship to the secure workspace runtime

The repository already contains a dedicated Docker workspace runtime that runs as a non-root developer user, drops Linux capabilities, disables networking, applies CPU, memory, and process limits, and keeps the Docker socket outside the public web service.

The local quick command is not a replacement for that security boundary. It provides instant offline inspection. The next sandbox phase will expose short-lived, command-scoped jobs through the existing isolated runtime and return verified artifacts to the same quick-check schema.

## Open protocol path

The installed package already exposes the standalone stdio command:

```bash
amosclaud-mcp
```

This allows an MCP-compatible client to use Amosclaud without Copilot or an IDE-specific host. The next Universal State Bridge phase will add the compact context and deterministic validation results as MCP resources and tools, then unify repository events, logs, build evidence, and deployment telemetry behind an open event schema.

## Staged delivery

The developer-experience program is intentionally split into focused changes:

1. Zero-config local context compression and guardrails.
2. Command-scoped ephemeral jobs on the isolated workspace runtime.
3. Drop-in GitHub Action and repository metric-card endpoints.
4. Universal State Bridge resources for MCP, REST, webhooks, and streaming events.
5. Public templates, starter repositories, and self-hosted open-core documentation.

Each stage must pass deterministic tests and security checks independently before it is merged.
