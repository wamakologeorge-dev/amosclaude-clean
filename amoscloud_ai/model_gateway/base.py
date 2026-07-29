"""Provider interface for the Amosclaud Universal Model Gateway."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .schemas import AmosModelRequest, AmosModelResponse, ModelCapabilities, ProviderHealth


class ModelProvider(ABC):
    """Synchronous provider contract used by the first gateway milestone."""

    key: str
    model: str
    capabilities: ModelCapabilities
    priority: int = 0

    @abstractmethod
    def health(self) -> ProviderHealth:
        """Return a bounded readiness result without exposing secrets."""

    @abstractmethod
    def generate(self, request: AmosModelRequest) -> AmosModelResponse:
        """Perform one inference and return a normalized response."""

    def supports(self, request: AmosModelRequest) -> tuple[bool, str]:
        return self.capabilities.supports(request)
