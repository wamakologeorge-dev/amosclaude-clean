# Amosclaud OpenAI-Compatible API

Amosclaud exposes an OpenAI-compatible API surface at your Amosclaud deployment
URL.

## Important

Amosclaud API keys are accepted by Amosclaud only. They are not valid
credentials for `https://api.openai.com/v1`.

Use the standard OpenAI SDK with the Amosclaud base URL:

```python
from openai import OpenAI

client = OpenAI(
    api_key="amos_aut_your_generated_key",
    base_url="https://www.amosclaud.com/v1",
)

response = client.responses.create(
    model="amosclaud-agent",
    input="Inspect my repository and explain the first verified blocker.",
)

print(response.output_text)
```

Chat-completions clients remain supported:

```python
response = client.chat.completions.create(
    model="amosclaud-agent",
    messages=[
        {"role": "user", "content": "Build a FastAPI endpoint."}
    ],
)
```

## Endpoints

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/responses`

The Responses endpoint currently supports non-streaming text input, message
input, instructions, metadata, and `max_output_tokens`. Streaming requests are
rejected explicitly instead of pretending to stream.

## Continue configuration

A ready-to-copy configuration is stored at:

```text
config/continue/amosclaud.yaml.example
```

It uses `https://www.amosclaud.com/v1`, the `amosclaud-agent` model, and the
Responses API.

## Server configuration

The Amosclaud server must have its own allowed-model list and, only when using
an OpenAI-hosted model, an upstream OpenAI credential:

```env
AMOSCLAUD_OPENAI_COMPAT_MODELS=amosclaud-agent,gpt-4.1-mini
OPENAI_API_KEY=server_side_openai_key
```

The user-facing Amosclaud key is validated by Amosclaud. Amosclaud then
performs any upstream model request with its private server-side credential.

## Security properties

- User keys are not forwarded to OpenAI.
- The upstream OpenAI key is never returned to clients.
- Requests are credit-checked before upstream execution.
- Failed upstream calls are refunded.
- OpenAI response storage is disabled for compatible upstream requests.
- Unknown models and unsupported streaming requests fail explicitly.
