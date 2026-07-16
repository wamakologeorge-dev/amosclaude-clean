# Amosclaud OpenAI-Compatible API

Amosclaud exposes an OpenAI-compatible API surface at your Amosclaud deployment URL.

## Important

Amosclaud API keys are accepted by Amosclaud only. They are not valid credentials for `https://api.openai.com/v1`.

Use the standard OpenAI SDK with the Amosclaud base URL:

```python
from openai import OpenAI

client = OpenAI(
    api_key="amos_aut_your_generated_key",
    base_url="https://amosclaud.com/v1",
)

response = client.chat.completions.create(
    model="gpt-4.1-mini",
    messages=[
        {"role": "user", "content": "Build a FastAPI endpoint."}
    ],
)

print(response.choices[0].message.content)
```

## Endpoints

- `GET /v1/models`
- `POST /v1/chat/completions`

## Server configuration

The Amosclaud server must have its own upstream OpenAI credential and allowed-model list:

```env
OPENAI_API_KEY=server_side_openai_key
AMOSCLAUD_OPENAI_COMPAT_MODELS=gpt-4.1-mini,amosclaud-agent
```

The user-facing Amosclaud key is validated by Amosclaud. Amosclaud then performs the upstream model request with its private server-side credential.

## Security properties

- User keys are not forwarded to OpenAI.
- The upstream OpenAI key is never returned to clients.
- Requests are credit-checked before upstream execution.
- Failed upstream calls are refunded.
- OpenAI response storage is disabled for compatible upstream requests.
