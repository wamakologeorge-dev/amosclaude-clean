"""Google Gemini generateContent provider."""

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


class GeminiProvider(ModelProvider):
    key = "gemini"

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
            input_modalities=frozenset({"text"}),
            max_context_tokens=0,
            privacy="external",
            supports_streaming=False,
        )

    def health(self) -> ProviderHealth:
        if not self.api_key:
            return ProviderHealth(status="unavailable", detail="GEMINI_API_KEY is not configured")
        if not self.model:
            return ProviderHealth(status="unavailable", detail="GEMINI_MODEL is not configured")
        return ProviderHealth(status="ready", detail="configured")

    def generate(self, request: AmosModelRequest) -> AmosModelResponse:
        system = "\n\n".join(
            message.content
            for message in request.messages
            if message.role in {"system", "developer"}
        )
        contents: list[dict[str, Any]] = []
        for message in request.messages:
            if message.role in {"system", "developer", "tool"}:
                continue
            role = "model" if message.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": message.content}]})

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": request.max_output_tokens},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if request.tools:
            declarations = []
            for tool in request.tools:
                function = tool.get("function")
                declarations.append(dict(function) if isinstance(function, dict) else dict(tool))
            payload["tools"] = [{"functionDeclarations": declarations}]

        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        client = self._client or httpx.Client(timeout=request.timeout_seconds)
        close_client = self._client is None
        started = monotonic()
        try:
            response = client.post(
                endpoint,
                headers={"x-goog-api-key": self.api_key},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        finally:
            if close_client:
                client.close()
        latency_ms = int((monotonic() - started) * 1000)

        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError("Gemini returned no candidates")
        candidate = candidates[0] or {}
        parts = (candidate.get("content") or {}).get("parts") or []
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for part in parts:
            if "text" in part:
                text_parts.append(str(part.get("text") or ""))
            if "functionCall" in part:
                tool_calls.append(dict(part["functionCall"]))
        usage = data.get("usageMetadata") or {}
        normalized_usage = {
            "input_tokens": int(usage.get("promptTokenCount") or 0),
            "output_tokens": int(usage.get("candidatesTokenCount") or 0),
            "total_tokens": int(usage.get("totalTokenCount") or 0),
        }
        return AmosModelResponse(
            content="".join(text_parts),
            provider=self.key,
            model=self.model,
            finish_reason=candidate.get("finishReason"),
            tool_calls=tuple(tool_calls),
            usage=normalized_usage,
            latency_ms=latency_ms,
            request_id=data.get("responseId"),
        )
