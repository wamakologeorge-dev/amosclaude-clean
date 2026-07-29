"""Compatibility adapter for the current Amosclaud provider runtime."""

from __future__ import annotations

from time import monotonic
from typing import Any

from ..base import ModelProvider
from ..schemas import (
    AmosModelRequest,
    AmosModelResponse,
    ModelCapabilities,
    ProviderHealth,
)


class LegacyAmosclaudProvider(ModelProvider):
    """Preserve today's first-party resolution path behind the new contract."""

    key = "amosclaud"
    model = "amosclaud-agent"
    priority = 100
    capabilities = ModelCapabilities(
        task_types=frozenset({"*"}),
        features=frozenset({"code", "reasoning", "tools", "repository_context"}),
        max_context_tokens=0,
        privacy="first_party",
        supports_streaming=False,
    )

    @staticmethod
    def _provider_module():
        from amoscloud_ai import provider

        return provider

    def health(self) -> ProviderHealth:
        probe = self._provider_module().probe()
        if bool(probe.get("ready")):
            return ProviderHealth(status="ready", detail=str(probe.get("runtime") or "ready"))
        detail = str(probe.get("detail") or "Amosclaud model runtime is unavailable")
        return ProviderHealth(status="unavailable", detail=detail[:300])

    def generate(self, request: AmosModelRequest) -> AmosModelResponse:
        provider = self._provider_module()
        system_parts: list[str] = []
        history: list[dict[str, str]] = []
        for message in request.messages:
            if message.role in {"system", "developer"}:
                system_parts.append(message.content)
                continue
            history.append({"role": message.role, "content": message.content})
        system_prompt = "\n\n".join(system_parts).strip()
        system_prompt = system_prompt or "You are Amosclaud Autonomous."

        started = monotonic()
        result = provider.reply(history, system_prompt)
        latency_ms = int((monotonic() - started) * 1000)
        if not getattr(result, "ok", False):
            raise RuntimeError(getattr(result, "error", None) or "Amosclaud runtime failed")
        usage: dict[str, int] = {}
        raw_usage: Any = getattr(result, "usage", None)
        if isinstance(raw_usage, dict):
            usage = {
                str(key): int(value) for key, value in raw_usage.items() if isinstance(value, int)
            }
        return AmosModelResponse(
            content=str(getattr(result, "reply", "")),
            provider=self.key,
            model=str(getattr(result, "model", None) or self.model),
            finish_reason=str(getattr(result, "finish_reason", None) or "stop"),
            usage=usage,
            latency_ms=latency_ms,
            request_id=getattr(result, "request_id", None),
        )
