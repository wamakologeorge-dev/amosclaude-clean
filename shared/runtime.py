"""Canonical service names and internal endpoint configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse


class ServiceName(str, Enum):
    PLATFORM = "amosclaud"
    MODEL = "model"
    CREDENTIAL_AUTHORITY = "credential-authority"
    METRICS = "metrics"
    REDIS = "redis"
    AUTONOMOUS_AGENT = "autonomous-agent"
    FIXER = "amosclaud-fixer"
    REPOSITORY = "repository"


@dataclass(frozen=True, slots=True)
class ServiceEndpoint:
    name: ServiceName
    base_url: str
    health_path: str = "/health"

    @property
    def health_url(self) -> str:
        return f"{self.base_url.rstrip('/')}{self.health_path}"

    def validate(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https", "redis"}:
            raise ValueError(f"Unsupported service URL scheme for {self.name.value}: {self.base_url}")
        if not parsed.hostname:
            raise ValueError(f"Service URL has no hostname for {self.name.value}: {self.base_url}")


def _env(name: str, default: str) -> str:
    value = os.getenv(name, default).strip()
    if not value:
        raise RuntimeError(f"{name} must not be empty")
    return value.rstrip("/")


def platform_endpoints() -> dict[ServiceName, ServiceEndpoint]:
    """Return the internal service map shared with Docker Compose.

    Agent and Fixer are capabilities hosted by the platform process today, so
    both resolve through the platform API rather than pretending to be separate
    containers with commands that do not exist.
    """

    platform_url = _env("AMOSCLAUD_API_URL", "http://amosclaud:8000")
    endpoints = {
        ServiceName.PLATFORM: ServiceEndpoint(ServiceName.PLATFORM, platform_url),
        ServiceName.MODEL: ServiceEndpoint(
            ServiceName.MODEL,
            _env("AMOSCLAUD_MODEL_URL", "http://model:8091"),
        ),
        ServiceName.CREDENTIAL_AUTHORITY: ServiceEndpoint(
            ServiceName.CREDENTIAL_AUTHORITY,
            _env("AMOSCLAUD_CREDENTIAL_URL", "http://credential-authority:8001"),
        ),
        ServiceName.METRICS: ServiceEndpoint(
            ServiceName.METRICS,
            _env("AMOSCLAUD_METRICS_URL", "http://metrics:9090"),
        ),
        ServiceName.REDIS: ServiceEndpoint(
            ServiceName.REDIS,
            _env("REDIS_URL", "redis://redis:6379/0"),
            health_path="",
        ),
        ServiceName.AUTONOMOUS_AGENT: ServiceEndpoint(ServiceName.AUTONOMOUS_AGENT, platform_url),
        ServiceName.FIXER: ServiceEndpoint(ServiceName.FIXER, platform_url),
        ServiceName.REPOSITORY: ServiceEndpoint(ServiceName.REPOSITORY, platform_url),
    }
    for endpoint in endpoints.values():
        endpoint.validate()
    return endpoints


REQUIRED_PLATFORM_ENV = frozenset(
    {
        "AMOSCLAUD_API_URL",
        "AMOSCLAUD_MODEL_URL",
        "AMOSCLAUD_CREDENTIAL_URL",
        "AMOSCLAUD_METRICS_URL",
        "AMOSCLAUD_REPOSITORIES_ROOT",
        "AMOSCLAUD_WORKSPACE",
        "DATABASE_URL",
        "REDIS_URL",
    }
)

SECRET_ENV_NAMES = frozenset(
    {
        "AMOSCLAUD_API_KEY",
        "AMOSCLAUD_MODEL_TOKEN",
        "AGENT_JWT_SECRET_KEY",
        "API_KEY_MANAGER_ADMIN_PASSWORD",
        "METRICS_SHARED_SECRET",
    }
)
