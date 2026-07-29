# Ollama API key in Amosclaud Actions

`OLLAMA_API_KEY` is a protected GitHub Actions secret for the repository. It is
not a repository file, a VS Code setting, or a device-local credential.

## Why this works from every device

GitHub stores the secret for the repository and injects it only into explicitly
configured workflow steps. A workflow therefore receives the same protected key
whether it is started from a desktop, Chromebook, phone, issue comment, pull
request, or scheduled event.

The key must be configured at:

```text
Repository Settings → Secrets and variables → Actions → Repository secrets
```

Use this exact name:

```text
OLLAMA_API_KEY
```

For direct Ollama Cloud access, the workflows use:

```text
OLLAMA_URL=https://ollama.com
AMOSCLAUD_MODEL_TOKEN=${OLLAMA_API_KEY}
AMOSCLAUD_MODEL=gpt-oss:120b
```

`OLLAMA_URL` can remain unset because the trusted connection check defaults to
`https://ollama.com`. Set it as a repository secret only when a different Ollama
host is intentionally required.

## Security boundary

Never put the API key in any of these locations:

- `.env`, `.env.local`, or another committed file;
- `settings.json`, `.vscode/settings.json`, or `mcp.json`;
- issue comments, pull requests, screenshots, terminal output, or workflow logs;
- Chromebook browser storage or a shared VS Code profile;
- workflow variables (`vars`) instead of workflow secrets (`secrets`).

The VS Code and Chromebook clients should authenticate to Amosclaud. Amosclaud's
backend and GitHub Actions use `OLLAMA_API_KEY` on the user's behalf. The raw key
must never be sent to the browser extension.

## Actions behavior

Before the GitHub model agent runs, `amosclaud_bot.ollama_connection` calls the
authenticated Ollama model-list endpoint. It confirms that the key works without
printing the key or returning it to an issue comment.

The model provider then receives the same value through the normalized
`AMOSCLAUD_MODEL_TOKEN` contract and sends it as:

```text
Authorization: Bearer <protected key>
```

If the repository secret is absent, the connection check reports that it was
skipped and the existing first-party or configured fallback route remains
available. If a configured key is rejected, the workflow stops before invoking
the model agent.

## Rotation

When the Ollama key is rotated, replace the value of the existing repository
secret. Do not rename it and do not commit any code change. All configured
Actions runs will use the replacement value automatically.
