"""Deterministic capability, privacy, health, and budget routing policy."""

from __future__ import annotations

from .base import ModelProvider
from .schemas import AmosModelRequest, ProviderHealth, RoutingDecision


class RoutingPolicy:
    """Score providers without hard-coding provider names into Autonomous."""

    def evaluate(
        self,
        provider: ModelProvider,
        request: AmosModelRequest,
        health: ProviderHealth,
    ) -> RoutingDecision:
        if health.status == "unavailable":
            return RoutingDecision(
                provider=provider.key,
                eligible=False,
                score=float("-inf"),
                reason=health.detail or "provider is unavailable",
            )

        supported, reason = provider.supports(request)
        if not supported:
            return RoutingDecision(
                provider=provider.key,
                eligible=False,
                score=float("-inf"),
                reason=reason,
            )

        estimated_cost = provider.capabilities.estimated_cost_usd(request)
        if (
            request.maximum_cost_usd is not None
            and estimated_cost is not None
            and estimated_cost > request.maximum_cost_usd
        ):
            return RoutingDecision(
                provider=provider.key,
                eligible=False,
                score=float("-inf"),
                reason="estimated cost exceeds the request budget",
                estimated_cost_usd=estimated_cost,
            )

        score = float(provider.priority)
        score += 100 if health.ready else 20
        if request.preferred_provider == provider.key:
            score += 1_000
        if provider.capabilities.privacy == "local":
            score += 80 if request.privacy_level != "public" else 20
        elif provider.capabilities.privacy == "first_party":
            score += 60 if request.privacy_level != "public" else 15
        if request.task_type in provider.capabilities.task_types:
            score += 40
        if request.required_capabilities:
            score += 10 * len(request.required_capabilities)
        if estimated_cost is not None:
            score -= min(estimated_cost * 10, 50)

        return RoutingDecision(
            provider=provider.key,
            eligible=True,
            score=score,
            reason="eligible",
            estimated_cost_usd=estimated_cost,
        )
