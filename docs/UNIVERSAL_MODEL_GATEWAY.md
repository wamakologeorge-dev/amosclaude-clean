# Amosclaud Universal Model Gateway

The Universal Model Gateway is the provider-neutral inference layer used by
**Amosclaud Autonomous**. Providers remain private implementation details; the
product continues to expose one Autonomous agent, one repository context, and
one evidence-backed result.

## Milestone 1 contract

The initial gateway introduces:

- normalized `AmosModelRequest` and `AmosModelResponse` schemas;
- a thread-safe provider registry;
- deterministic routing by health, task capability, privacy, preference, and
  request budget;
- bounded provider fallback with auditable routing decisions;
- compatibility with the existing first-party Amosclaud provider runtime;
- adapters for OpenAI-compatible endpoints, Anthropic, and Gemini;
- explicit opt-in for external providers through
  `AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS=true`.

The existing `amoscloud_ai.provider` runtime remains the production path during
this milestone. `LegacyAmosclaudProvider` wraps it behind the new contract so a
later migration can happen without changing the Autonomous user experience.

## Environment configuration

First-party and self-hosted model resolution continues to use the existing
Amosclaud variables. The new factory additionally recognizes:

- `AMOSCLAUD_OPENAI_COMPAT_URL`
- `AMOSCLAUD_OPENAI_COMPAT_MODEL`
- `AMOSCLAUD_OPENAI_COMPAT_TOKEN`
- `AMOSCLAUD_OPENAI_COMPAT_PRIVACY` (`local`, `first_party`, or `external`)
- `AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS`
- `OPENAI_API_KEY`, `OPENAI_MODEL`, and optional `OPENAI_BASE_URL`
- `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`
- `GEMINI_API_KEY` or `GOOGLE_API_KEY`, and `GEMINI_MODEL`

External adapters are not registered unless the explicit opt-in flag is true.
Private requests are routed only to local or first-party providers. Requests
marked `local_only` can run only on providers declaring local privacy.

## Example

```python
from amoscloud_ai.model_gateway import AmosMessage, AmosModelRequest, build_default_gateway

request = AmosModelRequest(
    messages=(AmosMessage(role="user", content="Explain the failing test"),),
    task_type="code",
    required_capabilities=frozenset({"code"}),
    privacy_level="private",
)

response = build_default_gateway().generate(request)
print(response.provider, response.model, response.content)
```

## Next integration step

After the foundation is proven in CI, the existing `provider.reply()` entrypoint
can delegate to the gateway behind a feature flag. The legacy provider remains a
fallback until equivalent readiness, response normalization, secret redaction,
and failure diagnostics are verified.
