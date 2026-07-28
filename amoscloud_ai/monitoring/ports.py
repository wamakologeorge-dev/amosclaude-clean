"""Application-facing ports for monitoring infrastructure."""
from __future__ import annotations

from typing import Protocol, Sequence

from .domain import AuditEvent, DeploymentEvent, HealthCheckResult, MetricSample


class HealthProbe(Protocol):
    name: str

    def run(self) -> HealthCheckResult: ...


class MonitoringRepository(Protocol):
    def initialize(self) -> None: ...

    def append_metric(self, sample: MetricSample) -> None: ...

    def list_metrics(
        self, *, name: str | None, organization_id: int | None, limit: int
    ) -> Sequence[MetricSample]: ...

    def append_deployment_event(self, event: DeploymentEvent) -> None: ...

    def list_deployment_events(
        self, *, organization_id: int | None, limit: int
    ) -> Sequence[DeploymentEvent]: ...

    def append_audit_event(self, event: AuditEvent) -> None: ...

    def list_audit_events(
        self, *, organization_id: int | None, limit: int
    ) -> Sequence[AuditEvent]: ...
