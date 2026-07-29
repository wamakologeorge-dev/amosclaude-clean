"""Universal model routing and bounded fallback execution."""

from __future__ import annotations

from dataclasses import dataclass

from .base import ModelProvider
from .policy import RoutingPolicy
from .registry import ProviderRegistry
from .schemas import AmosModelRequest, AmosModelResponse, ProviderHealth, RoutingDecision


@dataclass(frozen=True)
class ProviderAttempt:
    provider: str
    error_type: str
    detail: str


class GatewayUnavailableError(RuntimeError):
    """Raised when no eligible provider can return a response."""

    def __init__(
        self,
        message: str,
        *,
        decisions: tuple[RoutingDecision, ...] = (),
        attempts: tuple[ProviderAttempt, ...] = (),
    ) -> None:
        super().__init__(message)
        self.decisions = decisions
        self.attempts = attempts


class UniversalModelGateway:
    """One governed inference entrypoint for Amosclaud Autonomous."""

    def __init__(
        self,
        registry: ProviderRegistry | None = None,
        policy: RoutingPolicy | None = None,
    ) -> None:
        self.registry = registry or ProviderRegistry()
        self.policy = policy or RoutingPolicy()

    def route(
        self,
        request: AmosModelRequest,
    ) -> tuple[tuple[ModelProvider, RoutingDecision], ...]:
        evaluated: list[tuple[ModelProvider, RoutingDecision]] = []
        for provider in self.registry.providers():
            try:
                health = provider.health()
            except Exception as exc:  # defensive: provider health must not break routing
                health = ProviderHealth(
                    status="unavailable",
                    detail=f"health check failed: {type(exc).__name__}",
                )
            evaluated.append((provider, self.policy.evaluate(provider, request, health)))
        return tuple(
            sorted(
                evaluated,
                key=lambda item: (-item[1].score, item[0].key),
            )
        )

    def generate(self, request: AmosModelRequest) -> AmosModelResponse:
        routed = self.route(request)
        decisions = tuple(decision for _, decision in routed)
        eligible = [(provider, decision) for provider, decision in routed if decision.eligible]
        if not eligible:
            reasons = "; ".join(f"{decision.provider}: {decision.reason}" for decision in decisions)
            raise GatewayUnavailableError(
                f"no eligible model provider is available ({reasons})",
                decisions=decisions,
            )

        attempts: list[ProviderAttempt] = []
        for provider, _decision in eligible:
            try:
                response = provider.generate(request)
            except Exception as exc:
                attempts.append(
                    ProviderAttempt(
                        provider=provider.key,
                        error_type=type(exc).__name__,
                        detail=f"{type(exc).__name__}: provider request failed",
                    )
                )
                continue
            if response.provider != provider.key:
                response = AmosModelResponse(
                    content=response.content,
                    provider=provider.key,
                    model=response.model,
                    finish_reason=response.finish_reason,
                    tool_calls=response.tool_calls,
                    usage=response.usage,
                    latency_ms=response.latency_ms,
                    request_id=response.request_id,
                    raw=response.raw,
                )
            return response

        summary = "; ".join(f"{attempt.provider}: {attempt.error_type}" for attempt in attempts)
        raise GatewayUnavailableError(
            f"all eligible model providers failed ({summary})",
            decisions=decisions,
            attempts=tuple(attempts),
        )
