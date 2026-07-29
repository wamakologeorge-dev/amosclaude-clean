"""Unit tests for the provider-neutral Universal Model Gateway foundation."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import httpx
import pytest

from amoscloud_ai.model_gateway import (
    AmosMessage,
    AmosModelRequest,
    AmosModelResponse,
    GatewayUnavailableError,
    ModelCapabilities,
    ModelProvider,
    ProviderHealth,
    ProviderRegistry,
    UniversalModelGateway,
    build_default_gateway,
)
from amoscloud_ai.model_gateway.providers import (
    GeminiProvider,
    LegacyAmosclaudProvider,
    OpenAICompatibleProvider,
)


@dataclass
class FakeProvider(ModelProvider):
    key: str
    score_priority: int = 0
    privacy: str = "first_party"
    status: str = "ready"
    fail: bool = False
    content: str = "ok"

    def __post_init__(self):
        self.model = f"{self.key}-model"
        self.priority = self.score_priority
        self.capabilities = ModelCapabilities(
            task_types=frozenset({"*"}),
            features=frozenset({"code", "tools"}),
            privacy=self.privacy,  # type: ignore[arg-type]
            supports_streaming=True,
        )

    def health(self) -> ProviderHealth:
        return ProviderHealth(status=self.status, detail=self.status)  # type: ignore[arg-type]

    def generate(self, request: AmosModelRequest) -> AmosModelResponse:
        if self.fail:
            raise RuntimeError(f"{self.key} failed")
        return AmosModelResponse(
            content=self.content,
            provider=self.key,
            model=self.model,
        )


def request(**kwargs) -> AmosModelRequest:
    return AmosModelRequest(
        messages=(AmosMessage(role="user", content="Fix the failing tests"),),
        task_type="code",
        required_capabilities=frozenset({"code"}),
        **kwargs,
    )


def test_registry_rejects_duplicate_provider_keys():
    registry = ProviderRegistry()
    registry.register(FakeProvider("alpha"))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(FakeProvider("alpha"))


def test_preferred_provider_wins_when_it_is_eligible():
    registry = ProviderRegistry()
    registry.register(FakeProvider("first", score_priority=100))
    registry.register(FakeProvider("preferred", score_priority=0))
    gateway = UniversalModelGateway(registry=registry)

    response = gateway.generate(request(preferred_provider="preferred"))

    assert response.provider == "preferred"


def test_local_only_request_excludes_first_party_and_external_providers():
    registry = ProviderRegistry()
    registry.register(FakeProvider("external", privacy="external"))
    registry.register(FakeProvider("first-party", privacy="first_party"))
    gateway = UniversalModelGateway(registry=registry)

    with pytest.raises(GatewayUnavailableError) as error:
        gateway.generate(request(privacy_level="local_only"))

    assert all(not decision.eligible for decision in error.value.decisions)
    assert "local-only" in str(error.value)


def test_gateway_falls_back_after_a_provider_failure():
    registry = ProviderRegistry()
    registry.register(FakeProvider("primary", score_priority=100, fail=True))
    registry.register(FakeProvider("fallback", score_priority=10, content="recovered"))
    gateway = UniversalModelGateway(registry=registry)

    response = gateway.generate(request())

    assert response.provider == "fallback"
    assert response.content == "recovered"


def test_budget_rejects_provider_with_known_excess_cost():
    provider = FakeProvider("expensive")
    provider.capabilities = ModelCapabilities(
        task_types=frozenset({"*"}),
        features=frozenset({"code"}),
        privacy="first_party",
        estimated_input_cost_per_million_usd=100.0,
        estimated_output_cost_per_million_usd=100.0,
    )
    registry = ProviderRegistry()
    registry.register(provider)
    gateway = UniversalModelGateway(registry=registry)

    with pytest.raises(GatewayUnavailableError) as error:
        gateway.generate(
            request(
                estimated_input_tokens=10_000,
                max_output_tokens=10_000,
                maximum_cost_usd=0.10,
            )
        )

    assert "budget" in str(error.value)


def test_factory_requires_explicit_opt_in_for_external_adapters(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-secret")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret")
    monkeypatch.delenv("AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS", raising=False)

    gateway = build_default_gateway()

    assert gateway.registry.keys() == ("amosclaud",)

    monkeypatch.setenv("AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS", "true")
    enabled = build_default_gateway()
    assert set(enabled.registry.keys()) == {"amosclaud", "openai", "anthropic", "gemini"}


def test_openai_compatible_provider_normalizes_reply_and_tool_calls():
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode("utf-8")
        assert '"model":"test-model"' in body
        return httpx.Response(
            200,
            json={
                "id": "response-1",
                "model": "test-model",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {"name": "run_tests", "arguments": "{}"},
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        key="compatible",
        base_url="https://model.example/v1",
        model="test-model",
        api_key="secret",
        privacy="first_party",
        client=client,
    )

    response = provider.generate(request())

    assert response.provider == "compatible"
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls[0]["function"]["name"] == "run_tests"
    assert response.usage["prompt_tokens"] == 10
    client.close()


def test_gemini_provider_normalizes_text_usage_and_function_calls():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == "gemini-secret"
        assert "key" not in request.url.params
        return httpx.Response(
            200,
            json={
                "responseId": "gemini-response-1",
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {"text": "Done."},
                                {"functionCall": {"name": "run_tests", "args": {}}},
                            ]
                        },
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 20,
                    "candidatesTokenCount": 4,
                    "totalTokenCount": 24,
                },
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GeminiProvider(
        api_key="gemini-secret",
        model="gemini-test",
        client=client,
    )

    response = provider.generate(request())

    assert response.content == "Done."
    assert response.tool_calls[0]["name"] == "run_tests"
    assert response.usage["total_tokens"] == 24
    client.close()


def test_legacy_adapter_preserves_current_provider_contract(monkeypatch):
    fake_module = SimpleNamespace(
        probe=lambda: {"ready": True, "runtime": "self-hosted"},
        reply=lambda history, system: SimpleNamespace(
            ok=True,
            reply=f"{system}|{history[0]['content']}",
            model="legacy-model",
            finish_reason="stop",
            usage={"input_tokens": 3, "output_tokens": 2},
            request_id="legacy-1",
        ),
    )
    monkeypatch.setattr(
        LegacyAmosclaudProvider,
        "_provider_module",
        staticmethod(lambda: fake_module),
    )
    provider = LegacyAmosclaudProvider()
    model_request = AmosModelRequest(
        messages=(
            AmosMessage(role="system", content="System"),
            AmosMessage(role="developer", content="Developer"),
            AmosMessage(role="user", content="Hello"),
        ),
        task_type="code",
    )

    response = provider.generate(model_request)

    assert response.provider == "amosclaud"
    assert response.model == "legacy-model"
    assert response.content == "System\n\nDeveloper|Hello"
    assert response.usage["input_tokens"] == 3


def test_gateway_attempts_do_not_expose_provider_exception_text():
    class SecretFailure(FakeProvider):
        def generate(self, request: AmosModelRequest) -> AmosModelResponse:
            raise RuntimeError("Authorization: Bearer secret-token")

    registry = ProviderRegistry()
    registry.register(SecretFailure("secret-failure"))
    gateway = UniversalModelGateway(registry=registry)

    with pytest.raises(GatewayUnavailableError) as error:
        gateway.generate(request())

    assert "secret-token" not in str(error.value)
    assert "secret-token" not in error.value.attempts[0].detail
