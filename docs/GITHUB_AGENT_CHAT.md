# Amosclaud GitHub Agent Chat

Amosclaud has a GitHub-native conversational surface that lives in Issues and pull-request conversations.

## Start a dedicated chat

Open a new issue with the **Amosclaud Agent Chat** issue form. The issue is labeled `amosclaud-chat`, and Amosclaud replies in the same thread. The issue becomes the durable conversation record.

## Talk to Amosclaud from any issue or pull request

Create a comment that begins with one of these commands:

```text
/amosclaud explain this failure
/amosclaud status
/amosclaud fix repair the failing login tests
/amosclaud help
```

`@amosclaud` is also accepted as a trigger string even when there is no GitHub App account with that username. `/amosclaud` is the canonical command because it does not depend on a GitHub handle.

## Safety and execution

Normal chat is read-only. Comment text is treated as untrusted data and is never executed as shell. Credentials are redacted from model and GitHub error text.

`/amosclaud fix` is restricted to repository owners, members, and collaborators. It only works from an open same-repository pull request, pins the exact PR head SHA, and dispatches the existing `amosclaud-repair-control-plane.yml`. The chat controller does not push code, force-push, merge, deploy, or bypass verification.

## Model routing

The workflow prefers the existing Ollama configuration when `OLLAMA_API_KEY` is available:

- `OLLAMA_API_KEY`
- `OLLAMA_URL`
- `OLLAMA_MODEL`

Otherwise it uses the Amosclaud gateway:

- `AMOSCLAUD_API_KEY`
- `AMOSCLAUD_API_URL`
- `AMOSCLAUD_AGENT_MODEL`

The gateway must expose the OpenAI-compatible `/v1/chat/completions` contract already supported by Amosclaud.

## Conversation continuity

The controller sends a bounded recent window of the issue/PR conversation to the model. Amosclaud replies carry a hidden marker so prior assistant messages are recognized as assistant turns on future comments.

This creates a repository-owned chat history without a separate external chat database.
