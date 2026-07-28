"""Monitoring use cases independent of FastAPI and persistence details."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .domain import (
    AuditEvent,
    AuditOutcome,
    DeploymentEvent,
    DeploymentStatus,
    HealthCheckResult,
    HealthStatus,
    MetricSample,
    MonitoringSnapshot,
    utc_now,
)
from .ports import HealthProbe, MonitoringRepository

_SECRET_TERMS = ("authorization", "cookie", "password", "secret", "token", "api_key", "private_key")
_STATUS_WEIGHT = {
    HealthStatus.HEALTHY: 0,
    HealthStatus.UNKNOWN: 1,
    HealthStatus.DEGRADED: 2,
    HealthStatus.UNHEALTHY: 3,
}


def redact_metadata(value: object, *, depth: int = 0) -> object:
    """Bound and redact metadata before it can reach an audit or deployment log."""
    if depth >= 5:
        return "[depth-limited]"
    if isinstance(value, Mapping):
        output: dict[str, object] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 32:
                output["_truncated"] = True
                break
            name = str(key)[:100]
            if any(term in name.lower() for term in _SECRET_TERMS):
                output[name] = "[redacted]"
            else:
                output[name] = redact_metadata(item, depth=depth + 1)
        return output
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)[:32]
        return [redact_metadata(item, depth=depth + 1) for item in items]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:2_000]


class MonitoringService:
    def __init__(
        self,
        repository: MonitoringRepository,
        *,
        probes: Sequence[HealthProbe] = (),
    ) -> None:
        self._repository = repository
        self._probes = tuple(probes)

    def initialize(self) -> None:
        self._repository.initialize()

    def collect_health(
        self, *, actor_id: int | None = None, organization_id: int | None = None
    ) -> MonitoringSnapshot:
        checks: list[HealthCheckResult] = []
        for probe in self._probes:
            try:
                checks.append(probe.run())
            except Exception as exc:
                checks.append(
                    HealthCheckResult.create(
                        name=getattr(probe, "name", probe.__class__.__name__),
                        status=HealthStatus.UNHEALTHY,
                        summary="Health probe failed",
                        details={"error_type": type(exc).__name__},
                    )
                )
        status = max(
            (check.status for check in checks),
            key=lambda item: _STATUS_WEIGHT[item],
            default=HealthStatus.UNKNOWN,
        )
        snapshot = MonitoringSnapshot(status=status, checks=tuple(checks), generated_at=utc_now())
        self.record_audit(
            action="monitoring.health.collect",
            resource_type="monitoring_snapshot",
            resource_id=None,
            outcome=AuditOutcome.ALLOWED if status != HealthStatus.UNHEALTHY else AuditOutcome.FAILED,
            reason=f"Collected {len(checks)} monitoring checks with status {status.value}",
            metadata={"check_count": len(checks), "status": status.value},
            actor_id=actor_id,
            organization_id=organization_id,
        )
        return snapshot

    def record_metric(
        self,
        *,
        name: str,
        value: float,
        unit: str = "count",
        source: str = "amosclaud",
        labels: Mapping[str, str] | None = None,
        actor_id: int | None = None,
        organization_id: int | None = None,
    ) -> MetricSample:
        sample = MetricSample.create(
            name=name,
            value=value,
            unit=unit,
            source=source,
            labels=labels,
            organization_id=organization_id,
        )
        self._repository.append_metric(sample)
        self.record_audit(
            action="monitoring.metric.record",
            resource_type="metric_sample",
            resource_id=sample.id,
            outcome=AuditOutcome.ALLOWED,
            reason=f"Recorded metric {sample.name}",
            metadata={"name": sample.name, "source": sample.source, "unit": sample.unit},
            actor_id=actor_id,
            organization_id=organization_id,
        )
        return sample

    def list_metrics(
        self,
        *,
        name: str | None = None,
        organization_id: int | None = None,
        limit: int = 100,
    ) -> Sequence[MetricSample]:
        return self._repository.list_metrics(
            name=name,
            organization_id=organization_id,
            limit=max(1, min(int(limit), 1_000)),
        )

    def record_deployment_event(
        self,
        *,
        provider: str,
        service: str,
        environment: str,
        status: DeploymentStatus | str,
        message: str,
        revision: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        actor_id: int | None = None,
        organization_id: int | None = None,
    ) -> DeploymentEvent:
        event = DeploymentEvent.create(
            provider=provider,
            service=service,
            environment=environment,
            status=status,
            message=message,
            revision=revision,
            metadata=redact_metadata(metadata or {}),
            organization_id=organization_id,
        )
        self._repository.append_deployment_event(event)
        outcome = (
            AuditOutcome.FAILED
            if event.status in {DeploymentStatus.FAILED, DeploymentStatus.ROLLED_BACK}
            else AuditOutcome.ALLOWED
        )
        self.record_audit(
            action="monitoring.deployment.record",
            resource_type="deployment_event",
            resource_id=event.id,
            outcome=outcome,
            reason=f"Recorded {event.provider} deployment state {event.status.value}",
            metadata={
                "provider": event.provider,
                "service": event.service,
                "environment": event.environment,
                "status": event.status.value,
                "revision": event.revision,
            },
            actor_id=actor_id,
            organization_id=organization_id,
        )
        return event

    def list_deployment_events(
        self, *, organization_id: int | None = None, limit: int = 100
    ) -> Sequence[DeploymentEvent]:
        return self._repository.list_deployment_events(
            organization_id=organization_id,
            limit=max(1, min(int(limit), 1_000)),
        )

    def record_audit(
        self,
        *,
        action: str,
        resource_type: str,
        outcome: AuditOutcome | str,
        reason: str,
        resource_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        actor_id: int | None = None,
        organization_id: int | None = None,
    ) -> AuditEvent:
        event = AuditEvent.create(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            reason=reason,
            metadata=redact_metadata(metadata or {}),
            actor_id=actor_id,
            organization_id=organization_id,
        )
        self._repository.append_audit_event(event)
        return event

    def list_audit_events(
        self, *, organization_id: int | None = None, limit: int = 100
    ) -> Sequence[AuditEvent]:
        return self._repository.list_audit_events(
            organization_id=organization_id,
            limit=max(1, min(int(limit), 1_000)),
        )
