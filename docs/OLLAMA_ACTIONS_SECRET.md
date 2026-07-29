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

## Verified upstream route

Amosclaud uses two official Ollama interfaces:

```text
GET  https://ollama.com/api/tags
POST https://ollama.com/v1/chat/completions
```

The first checks authentication and model visibility. The second is the
OpenAI-compatible inference endpoint used by the Amosclaud provider.

A live repository issue-comment test returned:

```text
OLLAMA_UPSTREAM_READY
Provider: amosclaud
Runtime: self-hosted
Model: gpt-oss:120b
```

This proves that the repository secret, upstream hostname, bearer header, model
selection, GitHub Actions agent, and response path currently communicate end to
end.

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

The agent uses the same selected model for preflight and inference. Model
selection follows this order:

```text
vars.AMOSCLAUD_MODEL
vars.OLLAMA_MODEL
gpt-oss:120b
```

If the repository secret is absent, the connection check reports that it was
skipped and the existing first-party or configured fallback route remains
available. If a configured key is rejected or the selected model is not visible,
the workflow stops before invoking the model agent.

## Custom Amosclaud model

The repository contains:

```text
models/ollama/Modelfile
scripts/publish_ollama_model.sh
```

The canonical model name is lowercase and includes an explicit tag:

```text
wamakologeorge/amosclaud-clean:latest
```

Build and publish it from a machine that has Ollama installed and is signed into
the `wamakologeorge` Ollama account:

```bash
bash scripts/publish_ollama_model.sh
```

The script performs the equivalent of:

```bash
ollama pull llama3.2
ollama create wamakologeorge/amosclaud-clean:latest \
  -f models/ollama/Modelfile
ollama run wamakologeorge/amosclaud-clean:latest \
  "Reply with exactly: AMOSCLAUD_MODEL_READY"
ollama push wamakologeorge/amosclaud-clean:latest
```

An existing local model can instead be copied and pushed:

```bash
ollama cp llama3.2 wamakologeorge/amosclaud-clean:latest
ollama push wamakologeorge/amosclaud-clean:latest
```

`OLLAMA_API_KEY` authenticates direct programmatic calls to Ollama Cloud. The
`ollama push` CLI additionally requires the Ollama account to be signed in and
its Ollama public key to be registered with the account. The repository secret
must not be written into the Modelfile or publish script.

After publishing, run the **Ollama Model Verify** workflow with:

```text
wamakologeorge/amosclaud-clean:latest
```

That workflow requires the model to appear in `/api/tags` and requires a real
completion from `/v1/chat/completions`. Only after both checks pass should the
repository Actions variable be changed to:

```text
AMOSCLAUD_MODEL=wamakologeorge/amosclaud-clean:latest
```

If Ollama Cloud does not serve the custom published model through the cloud
completion endpoint, leave `AMOSCLAUD_MODEL=gpt-oss:120b`. The custom model can
still be pulled into a dedicated Amosclaud model station and used through that
station's OpenAI-compatible endpoint.

## Rotation

When the Ollama key is rotated, replace the value of the existing repository
secret. Do not rename it and do not commit any code change. All configured
Actions runs will use the replacement value automatically.
