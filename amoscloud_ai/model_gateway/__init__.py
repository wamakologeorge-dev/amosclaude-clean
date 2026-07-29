"""Amosclaud Universal Model Gateway public contract."""

from .base import ModelProvider
from .factory import build_default_gateway
from .policy import RoutingPolicy
from .registry import ProviderRegistry
from .router import GatewayUnavailableError, ProviderAttempt, UniversalModelGateway
from .schemas import (
    AmosMessage,
    AmosModelRequest,
    AmosModelResponse,
    ModelCapabilities,
    ProviderHealth,
    RoutingDecision,
)

__all__ = [
    "AmosMessage",
    "AmosModelRequest",
    "AmosModelResponse",
    "GatewayUnavailableError",
    "ModelCapabilities",
    "ModelProvider",
    "ProviderAttempt",
    "ProviderHealth",
    "ProviderRegistry",
    "RoutingDecision",
    "RoutingPolicy",
    "UniversalModelGateway",
    "build_default_gateway",
]
