"""OpenAI-compatible chat-completions provider."""

from __future__ import annotations

from time import monotonic
from typing import Any

import httpx

from ..base import ModelProvider
from ..schemas import (
    AmosModelRequest,
    AmosModelResponse,
    ModelCapabilities,
    ProviderHealth,
)


class OpenAICompatibleProvider(ModelProvider):
    """Connect OpenAI, local servers, and compatible hosted runtimes."""

    def __init__(
        self,
        *,
        key: str,
        base_url: str,
        model: str,
        api_key: str = "",
        priority: int = 0,
        privacy: str = "external",
        task_types: frozenset[str] = frozenset({"*"}),
        features: frozenset[str] = frozenset({"code", "reasoning", "tools"}),
        max_context_tokens: int = 0,
        supports_streaming: bool = False,
        estimated_input_cost_per_million_usd: float | None = None,
        estimated_output_cost_per_million_usd: float | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.key = key.strip().lower()
        self.base_url = base_url.rstrip("/")
        self.model = model.strip()
        self.api_key = api_key.strip()
        self.priority = priority
        self.capabilities = ModelCapabilities(
            task_types=task_types,
            features=features,
            max_context_tokens=max_context_tokens,
            privacy=privacy,  # type: ignore[arg-type]
            supports_streaming=supports_streaming,
            estimated_input_cost_per_million_usd=estimated_input_cost_per_million_usd,
            estimated_output_cost_per_million_usd=estimated_output_cost_per_million_usd,
        )
        self._client = client

    def health(self) -> ProviderHealth:
        if not self.base_url:
            return ProviderHealth(
                status="unavailable", detail="provider endpoint is not configured"
            )
        if not self.model:
            return ProviderHealth(status="unavailable", detail="provider model is not configured")
        return ProviderHealth(status="ready", detail="configured")

    def _endpoint(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/v1/chat/completions"

    def generate(self, request: AmosModelRequest) -> AmosModelResponse:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [message.to_dict() for message in request.messages],
            "max_tokens": request.max_output_tokens,
            "stream": False,
        }
        if request.tools:
            payload["tools"] = [dict(tool) for tool in request.tools]

        started = monotonic()
        client = self._client or httpx.Client(timeout=request.timeout_seconds)
        close_client = self._client is None
        try:
            response = client.post(self._endpoint(), headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        finally:
            if close_client:
                client.close()
        latency_ms = int((monotonic() - started) * 1000)

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("OpenAI-compatible provider returned no choices")
        choice = choices[0] or {}
        message = choice.get("message") or {}
        content = message.get("content") or ""
        tool_calls = tuple(message.get("tool_calls") or ())
        usage = data.get("usage") or {}
        return AmosModelResponse(
            content=str(content),
            provider=self.key,
            model=str(data.get("model") or self.model),
            finish_reason=choice.get("finish_reason"),
            tool_calls=tool_calls,
            usage={str(key): int(value) for key, value in usage.items() if isinstance(value, int)},
            latency_ms=latency_ms,
            request_id=data.get("id"),
            raw={"object": data.get("object")},
        )
