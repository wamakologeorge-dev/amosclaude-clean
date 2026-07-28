from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from amoscloud_ai.api.routes import monitoring as monitoring_routes
from amoscloud_ai.monitoring import (
    DeploymentStatus,
    HealthCheckResult,
    HealthStatus,
    MonitoringService,
    SQLiteMonitoringRepository,
    redact_metadata,
)


class StaticProbe:
    def __init__(self, name: str, status: HealthStatus) -> None:
        self.name = name
        self.status = status

    def run(self) -> HealthCheckResult:
        return HealthCheckResult.create(
            name=self.name,
            status=self.status,
            summary=f"{self.name} is {self.status.value}",
            details={"checked": True},
        )


def build_service(path: Path) -> MonitoringService:
    service = MonitoringService(
        SQLiteMonitoringRepository(path),
        probes=(
            StaticProbe("api", HealthStatus.HEALTHY),
            StaticProbe("database", HealthStatus.UNHEALTHY),
        ),
    )
    service.initialize()
    return service


def test_health_aggregation_and_audit_persistence(tmp_path: Path) -> None:
    service = build_service(tmp_path / "monitoring.db")
    snapshot = service.collect_health(actor_id=7)

    assert snapshot.status is HealthStatus.UNHEALTHY
    assert [check.name for check in snapshot.checks] == ["api", "database"]
    audits = service.list_audit_events()
    assert audits[0].actor_id == 7
    assert audits[0].action == "monitoring.health.collect"
    assert audits[0].outcome.value == "failed"


def test_metric_deployment_and_secret_redaction(tmp_path: Path) -> None:
    service = build_service(tmp_path / "monitoring.db")
    metric = service.record_metric(
        name="amosclaud_queue_depth",
        value=4,
        unit="jobs",
        source="worker",
        labels={"queue": "autonomous"},
        organization_id=9,
    )
    deployment = service.record_deployment_event(
        provider="railway",
        service="amosclaud-api",
        environment="production",
        status=DeploymentStatus.SUCCEEDED,
        revision="abc123",
        message="Release completed",
        metadata={"region": "us-west", "api_token": "never-store-this"},
        organization_id=9,
    )

    assert service.list_metrics(name=metric.name, organization_id=9)[0].value == 4
    stored = service.list_deployment_events(organization_id=9)[0]
    assert stored.id == deployment.id
    assert stored.metadata["api_token"] == "[redacted]"
    assert any(item.resource_id == deployment.id for item in service.list_audit_events(organization_id=9))


def test_metadata_redaction_is_recursive_and_bounded() -> None:
    result = redact_metadata(
        {
            "authorization": "Bearer private",
            "nested": {"password": "private", "safe": "visible"},
        }
    )
    assert result["authorization"] == "[redacted]"
    assert result["nested"]["password"] == "[redacted]"
    assert result["nested"]["safe"] == "visible"


def test_monitoring_router_requires_admin_and_accepts_ingest_token(
    tmp_path: Path, monkeypatch
) -> None:
    service = build_service(tmp_path / "monitoring.db")
    monkeypatch.setattr(monitoring_routes, "get_monitoring_service", lambda: service)
    monkeypatch.setattr(
        monitoring_routes,
        "get_user_from_session",
        lambda token: {"id": 1, "is_admin": 1} if token == "admin-session" else None,
    )
    monkeypatch.setenv("AMOSCLAUD_MONITORING_INGEST_TOKEN", "ingest-secret")

    app = FastAPI()
    app.include_router(monitoring_routes.router, prefix="/api/v1")
    with TestClient(app) as client:
        assert client.get("/api/v1/monitoring/audit/events").status_code == 401

        metric_response = client.post(
            "/api/v1/monitoring/metrics",
            headers={"Authorization": "Bearer ingest-secret"},
            json={
                "name": "amosclaud_build_duration_seconds",
                "value": 12.5,
                "unit": "seconds",
                "source": "github-actions",
                "labels": {"workflow": "build"},
            },
        )
        assert metric_response.status_code == 201

        client.cookies.set("amos_session", "admin-session")
        metrics = client.get("/api/v1/monitoring/metrics")
        audits = client.get("/api/v1/monitoring/audit/events")

    assert metrics.status_code == 200
    assert metrics.json()["count"] == 1
    assert audits.status_code == 200
    assert audits.json()["count"] >= 1


def test_monitoring_router_contract_is_complete() -> None:
    paths = {route.path for route in monitoring_routes.router.routes}
    assert {
        "/monitoring/health",
        "/monitoring/metrics",
        "/monitoring/deployments/events",
        "/monitoring/audit/events",
    }.issubset(paths)
