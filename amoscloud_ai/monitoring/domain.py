"""Framework-free monitoring and audit domain models."""
from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Mapping

_METRIC_NAME = re.compile(r"^[A-Za-z_:][A-Za-z0-9_:.-]{0,127}$")
_TEXT_LIMIT = 500


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _bounded_text(value: str, *, field_name: str, maximum: int = _TEXT_LIMIT) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{field_name} is required")
    if len(cleaned) > maximum:
        raise ValueError(f"{field_name} exceeds {maximum} characters")
    return cleaned


def _metadata(values: Mapping[str, object] | None, *, maximum_items: int = 32) -> Mapping[str, object]:
    source = dict(values or {})
    if len(source) > maximum_items:
        raise ValueError(f"metadata exceeds {maximum_items} items")
    return MappingProxyType(source)


def _labels(values: Mapping[str, str] | None) -> Mapping[str, str]:
    source = {str(key): str(value) for key, value in dict(values or {}).items()}
    if len(source) > 16:
        raise ValueError("labels exceed 16 items")
    for key, value in source.items():
        if not key or len(key) > 64 or len(value) > 128:
            raise ValueError("metric labels must use non-empty keys <=64 and values <=128 characters")
    return MappingProxyType(source)


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class AuditOutcome(str, Enum):
    ALLOWED = "allowed"
    DENIED = "denied"
    FAILED = "failed"


class DeploymentStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True, slots=True)
class HealthCheckResult:
    name: str
    status: HealthStatus
    summary: str
    observed_at: datetime = field(default_factory=utc_now)
    latency_ms: float | None = None
    details: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def create(
        cls,
        *,
        name: str,
        status: HealthStatus | str,
        summary: str,
        observed_at: datetime | None = None,
        latency_ms: float | None = None,
        details: Mapping[str, object] | None = None,
    ) -> "HealthCheckResult":
        if latency_ms is not None and (not math.isfinite(latency_ms) or latency_ms < 0):
            raise ValueError("latency_ms must be a finite non-negative number")
        return cls(
            name=_bounded_text(name, field_name="health check name", maximum=100),
            status=HealthStatus(status),
            summary=_bounded_text(summary, field_name="health check summary"),
            observed_at=observed_at or utc_now(),
            latency_ms=latency_ms,
            details=_metadata(details),
        )


@dataclass(frozen=True, slots=True)
class MonitoringSnapshot:
    status: HealthStatus
    checks: tuple[HealthCheckResult, ...]
    generated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class MetricSample:
    id: str
    name: str
    value: float
    unit: str
    source: str
    labels: Mapping[str, str]
    recorded_at: datetime
    organization_id: int | None = None

    @classmethod
    def create(
        cls,
        *,
        name: str,
        value: float,
        unit: str = "count",
        source: str = "amosclaud",
        labels: Mapping[str, str] | None = None,
        recorded_at: datetime | None = None,
        organization_id: int | None = None,
    ) -> "MetricSample":
        cleaned_name = str(name or "").strip()
        if not _METRIC_NAME.fullmatch(cleaned_name):
            raise ValueError("metric name is invalid")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("metric value must be finite")
        return cls(
            id=f"metric_{uuid.uuid4().hex}",
            name=cleaned_name,
            value=numeric,
            unit=_bounded_text(unit, field_name="metric unit", maximum=40),
            source=_bounded_text(source, field_name="metric source", maximum=100),
            labels=_labels(labels),
            recorded_at=recorded_at or utc_now(),
            organization_id=organization_id,
        )


@dataclass(frozen=True, slots=True)
class DeploymentEvent:
    id: str
    provider: str
    service: str
    environment: str
    status: DeploymentStatus
    revision: str | None
    message: str
    metadata: Mapping[str, object]
    created_at: datetime
    organization_id: int | None = None

    @classmethod
    def create(
        cls,
        *,
        provider: str,
        service: str,
        environment: str,
        status: DeploymentStatus | str,
        message: str,
        revision: str | None = None,
        metadata: Mapping[str, object] | None = None,
        created_at: datetime | None = None,
        organization_id: int | None = None,
    ) -> "DeploymentEvent":
        cleaned_revision = str(revision).strip() if revision is not None else None
        if cleaned_revision and len(cleaned_revision) > 160:
            raise ValueError("deployment revision exceeds 160 characters")
        return cls(
            id=f"deploy_{uuid.uuid4().hex}",
            provider=_bounded_text(provider, field_name="deployment provider", maximum=80),
            service=_bounded_text(service, field_name="deployment service", maximum=160),
            environment=_bounded_text(environment, field_name="deployment environment", maximum=80),
            status=DeploymentStatus(status),
            revision=cleaned_revision or None,
            message=_bounded_text(message, field_name="deployment message", maximum=2_000),
            metadata=_metadata(metadata),
            created_at=created_at or utc_now(),
            organization_id=organization_id,
        )


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: str
    action: str
    resource_type: str
    resource_id: str | None
    outcome: AuditOutcome
    reason: str
    metadata: Mapping[str, object]
    created_at: datetime
    actor_id: int | None = None
    organization_id: int | None = None

    @classmethod
    def create(
        cls,
        *,
        action: str,
        resource_type: str,
        outcome: AuditOutcome | str,
        reason: str,
        resource_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
        created_at: datetime | None = None,
        actor_id: int | None = None,
        organization_id: int | None = None,
    ) -> "AuditEvent":
        cleaned_resource_id = str(resource_id).strip() if resource_id is not None else None
        if cleaned_resource_id and len(cleaned_resource_id) > 200:
            raise ValueError("resource_id exceeds 200 characters")
        return cls(
            id=f"audit_{uuid.uuid4().hex}",
            action=_bounded_text(action, field_name="audit action", maximum=160),
            resource_type=_bounded_text(resource_type, field_name="audit resource type", maximum=100),
            resource_id=cleaned_resource_id or None,
            outcome=AuditOutcome(outcome),
            reason=_bounded_text(reason, field_name="audit reason", maximum=2_000),
            metadata=_metadata(metadata),
            created_at=created_at or utc_now(),
            actor_id=actor_id,
            organization_id=organization_id,
        )
