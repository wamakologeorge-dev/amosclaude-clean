"""Anthropic Messages API provider."""

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


class AnthropicProvider(ModelProvider):
    key = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        priority: int = 0,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.priority = priority
        self._client = client
        self.capabilities = ModelCapabilities(
            task_types=frozenset({"*"}),
            features=frozenset({"code", "reasoning", "tools", "long_context"}),
            max_context_tokens=0,
            privacy="external",
            supports_streaming=False,
        )

    def health(self) -> ProviderHealth:
        if not self.api_key:
            return ProviderHealth(
                status="unavailable", detail="ANTHROPIC_API_KEY is not configured"
            )
        if not self.model:
            return ProviderHealth(status="unavailable", detail="ANTHROPIC_MODEL is not configured")
        return ProviderHealth(status="ready", detail="configured")

    def generate(self, request: AmosModelRequest) -> AmosModelResponse:
        system = "\n\n".join(
            message.content
            for message in request.messages
            if message.role in {"system", "developer"}
        )
        messages = [
            {"role": message.role, "content": message.content}
            for message in request.messages
            if message.role not in {"system", "developer", "tool"}
        ]
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_output_tokens,
            "messages": messages,
        }
        if system:
            payload["system"] = system
        if request.tools:
            normalized_tools: list[dict[str, Any]] = []
            for tool in request.tools:
                function = tool.get("function")
                source = dict(function) if isinstance(function, dict) else dict(tool)
                parameters = source.pop("parameters", None)
                if parameters is not None:
                    source["input_schema"] = parameters
                source.pop("type", None)
                normalized_tools.append(source)
            payload["tools"] = normalized_tools

        client = self._client or httpx.Client(timeout=request.timeout_seconds)
        close_client = self._client is None
        started = monotonic()
        try:
            response = client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        finally:
            if close_client:
                client.close()
        latency_ms = int((monotonic() - started) * 1000)

        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in data.get("content") or []:
            if block.get("type") == "text":
                text_parts.append(str(block.get("text") or ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(dict(block))
        usage = data.get("usage") or {}
        return AmosModelResponse(
            content="".join(text_parts),
            provider=self.key,
            model=str(data.get("model") or self.model),
            finish_reason=data.get("stop_reason"),
            tool_calls=tuple(tool_calls),
            usage={str(key): int(value) for key, value in usage.items() if isinstance(value, int)},
            latency_ms=latency_ms,
            request_id=data.get("id"),
        )
