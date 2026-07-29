"""Normalized request, response, capability, and routing contracts.

The gateway deliberately uses small dataclasses instead of provider SDK types so
Amosclaud Autonomous owns one stable internal contract regardless of which model
runtime performs the inference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Mapping

MessageRole = Literal["system", "developer", "user", "assistant", "tool"]
PrivacyLevel = Literal["public", "private", "local_only"]
ProviderPrivacy = Literal["local", "first_party", "external"]
HealthStatus = Literal["ready", "degraded", "unavailable"]


def _frozen_mapping(value: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


@dataclass(frozen=True)
class AmosMessage:
    """One normalized conversational message."""

    role: MessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        if self.role not in {"system", "developer", "user", "assistant", "tool"}:
            raise ValueError(f"unsupported message role: {self.role}")
        if not self.content.strip():
            raise ValueError("message content cannot be empty")

    def to_dict(self) -> dict[str, str]:
        payload = {"role": self.role, "content": self.content}
        if self.name:
            payload["name"] = self.name
        if self.tool_call_id:
            payload["tool_call_id"] = self.tool_call_id
        return payload


@dataclass(frozen=True)
class ModelCapabilities:
    """Provider capabilities used for deterministic routing decisions."""

    task_types: frozenset[str] = frozenset({"general"})
    features: frozenset[str] = frozenset()
    input_modalities: frozenset[str] = frozenset({"text"})
    output_modalities: frozenset[str] = frozenset({"text"})
    max_context_tokens: int = 0
    privacy: ProviderPrivacy = "external"
    supports_streaming: bool = False
    estimated_input_cost_per_million_usd: float | None = None
    estimated_output_cost_per_million_usd: float | None = None

    def __post_init__(self) -> None:
        if self.privacy not in {"local", "first_party", "external"}:
            raise ValueError(f"unsupported provider privacy: {self.privacy}")
        if self.max_context_tokens < 0:
            raise ValueError("max_context_tokens cannot be negative")

    def supports(self, request: "AmosModelRequest") -> tuple[bool, str]:
        if request.task_type not in self.task_types and "*" not in self.task_types:
            return False, f"task type '{request.task_type}' is unsupported"
        missing = request.required_capabilities.difference(self.features)
        if missing:
            return False, f"missing capabilities: {', '.join(sorted(missing))}"
        if request.stream and not self.supports_streaming:
            return False, "streaming is unsupported"
        if request.privacy_level == "local_only" and self.privacy != "local":
            return False, "local-only data cannot leave the local runtime"
        if request.privacy_level == "private" and self.privacy == "external":
            return False, "private data requires a local or first-party runtime"
        estimated_tokens = request.estimated_input_tokens
        if self.max_context_tokens and estimated_tokens > self.max_context_tokens:
            return False, "estimated input exceeds the provider context window"
        return True, "supported"

    def estimated_cost_usd(self, request: "AmosModelRequest") -> float | None:
        if self.estimated_input_cost_per_million_usd is None:
            return None
        input_cost = (
            request.estimated_input_tokens / 1_000_000 * self.estimated_input_cost_per_million_usd
        )
        output_rate = self.estimated_output_cost_per_million_usd
        if output_rate is None:
            return input_cost
        output_cost = request.max_output_tokens / 1_000_000 * output_rate
        return input_cost + output_cost


@dataclass(frozen=True)
class AmosModelRequest:
    """Provider-neutral inference request owned by Amosclaud Autonomous."""

    messages: tuple[AmosMessage, ...]
    task_type: str = "general"
    required_capabilities: frozenset[str] = frozenset()
    tools: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=_frozen_mapping)
    privacy_level: PrivacyLevel = "private"
    preferred_provider: str | None = None
    maximum_cost_usd: float | None = None
    estimated_input_tokens: int = 0
    max_output_tokens: int = 1200
    timeout_seconds: float = 60.0
    stream: bool = False

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("at least one message is required")
        if not self.task_type.strip():
            raise ValueError("task_type cannot be empty")
        if self.maximum_cost_usd is not None and self.maximum_cost_usd < 0:
            raise ValueError("maximum_cost_usd cannot be negative")
        if self.estimated_input_tokens < 0:
            raise ValueError("estimated_input_tokens cannot be negative")
        if self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        object.__setattr__(self, "metadata", _frozen_mapping(self.metadata))
        object.__setattr__(
            self,
            "tools",
            tuple(_frozen_mapping(tool) for tool in self.tools),
        )

    @classmethod
    def from_history(
        cls,
        history: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> "AmosModelRequest":
        messages = [AmosMessage(role="system", content=system_prompt)]
        messages.extend(
            AmosMessage(
                role=str(item.get("role") or "user"),  # type: ignore[arg-type]
                content=str(item.get("content") or ""),
            )
            for item in history
        )
        return cls(messages=tuple(messages), **kwargs)


@dataclass(frozen=True)
class AmosModelResponse:
    """Normalized inference result returned to Amosclaud Autonomous."""

    content: str
    provider: str
    model: str
    finish_reason: str | None = None
    tool_calls: tuple[Mapping[str, Any], ...] = ()
    usage: Mapping[str, int] = field(default_factory=_frozen_mapping)
    latency_ms: int = 0
    request_id: str | None = None
    raw: Mapping[str, Any] = field(default_factory=_frozen_mapping)

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("provider cannot be empty")
        if not self.model.strip():
            raise ValueError("model cannot be empty")
        if self.latency_ms < 0:
            raise ValueError("latency_ms cannot be negative")
        object.__setattr__(self, "usage", _frozen_mapping(self.usage))
        object.__setattr__(self, "raw", _frozen_mapping(self.raw))
        object.__setattr__(
            self,
            "tool_calls",
            tuple(_frozen_mapping(call) for call in self.tool_calls),
        )


@dataclass(frozen=True)
class ProviderHealth:
    """One provider's readiness state without leaking credentials."""

    status: HealthStatus
    detail: str = ""

    @property
    def ready(self) -> bool:
        return self.status == "ready"


@dataclass(frozen=True)
class RoutingDecision:
    """Auditable score and eligibility result for one provider."""

    provider: str
    eligible: bool
    score: float
    reason: str
    estimated_cost_usd: float | None = None
