"""Authenticated interface adapter for monitoring, deployment evidence, and audit logs."""
from __future__ import annotations

import hmac
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from amosclaud_metrics.registry import registry as prometheus_registry
from amoscloud_ai.api.routes.auth import get_user_from_session
from amoscloud_ai.monitoring import (
    AuditOutcome,
    DeploymentStatus,
    MonitoringService,
    SQLiteMonitoringRepository,
    build_default_probes,
)

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


class MetricCreate(BaseModel):
    name: str = Field(min_length=3, max_length=128)
    value: float
    unit: str = Field(default="count", min_length=1, max_length=40)
    source: str = Field(default="amosclaud", min_length=1, max_length=100)
    labels: dict[str, str] = Field(default_factory=dict)
    organization_id: int | None = Field(default=None, ge=1)


class DeploymentEventCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=80)
    service: str = Field(min_length=1, max_length=160)
    environment: str = Field(min_length=1, max_length=80)
    status: DeploymentStatus
    revision: str | None = Field(default=None, max_length=160)
    message: str = Field(min_length=1, max_length=2_000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    organization_id: int | None = Field(default=None, ge=1)


class AuditEventCreate(BaseModel):
    action: str = Field(min_length=1, max_length=160)
    resource_type: str = Field(min_length=1, max_length=100)
    resource_id: str | None = Field(default=None, max_length=200)
    outcome: AuditOutcome
    reason: str = Field(min_length=1, max_length=2_000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    organization_id: int | None = Field(default=None, ge=1)


@lru_cache(maxsize=1)
def get_monitoring_service() -> MonitoringService:
    repository = SQLiteMonitoringRepository(
        Path(os.getenv("AMOSCLAUD_MONITORING_DB_PATH", "data/monitoring.db"))
    )
    service = MonitoringService(repository, probes=build_default_probes())
    service.initialize()
    return service


def _session_user(request: Request):
    return get_user_from_session(request.cookies.get("amos_session"))


def _admin_actor(request: Request) -> int:
    user = _session_user(request)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in required")
    if not bool(user["is_admin"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    return int(user["id"])


def _ingest_actor(request: Request, authorization: str | None) -> int | None:
    user = _session_user(request)
    if user and bool(user["is_admin"]):
        return int(user["id"])

    expected = os.getenv("AMOSCLAUD_MONITORING_INGEST_TOKEN", "").strip()
    supplied = authorization or ""
    if expected and hmac.compare_digest(supplied, f"Bearer {expected}"):
        return None
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Monitoring ingestion is not configured; use an administrator session",
        )
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid monitoring credential")


def _health_payload(snapshot) -> dict[str, Any]:
    return {
        "status": snapshot.status.value,
        "generated_at": snapshot.generated_at.isoformat(),
        "checks": [
            {
                "name": check.name,
                "status": check.status.value,
                "summary": check.summary,
                "observed_at": check.observed_at.isoformat(),
                "latency_ms": check.latency_ms,
                "details": dict(check.details),
            }
            for check in snapshot.checks
        ],
    }


def _metric_payload(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "organization_id": item.organization_id,
        "name": item.name,
        "value": item.value,
        "unit": item.unit,
        "source": item.source,
        "labels": dict(item.labels),
        "recorded_at": item.recorded_at.isoformat(),
    }


def _deployment_payload(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "organization_id": item.organization_id,
        "provider": item.provider,
        "service": item.service,
        "environment": item.environment,
        "status": item.status.value,
        "revision": item.revision,
        "message": item.message,
        "metadata": dict(item.metadata),
        "created_at": item.created_at.isoformat(),
    }


def _audit_payload(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "actor_id": item.actor_id,
        "organization_id": item.organization_id,
        "action": item.action,
        "resource_type": item.resource_type,
        "resource_id": item.resource_id,
        "outcome": item.outcome.value,
        "reason": item.reason,
        "metadata": dict(item.metadata),
        "created_at": item.created_at.isoformat(),
    }


@router.get("/health", summary="Collect current platform health evidence")
def monitoring_health(request: Request) -> dict[str, Any]:
    actor_id = _admin_actor(request)
    return _health_payload(get_monitoring_service().collect_health(actor_id=actor_id))


@router.post("/metrics", status_code=status.HTTP_201_CREATED, summary="Record a metric sample")
def create_metric(
    body: MetricCreate,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor_id = _ingest_actor(request, authorization)
    if not body.name.startswith("amosclaud_"):
        raise HTTPException(status_code=422, detail="Metric names must start with amosclaud_")
    try:
        item = get_monitoring_service().record_metric(
            name=body.name,
            value=body.value,
            unit=body.unit,
            source=body.source,
            labels=body.labels,
            actor_id=actor_id,
            organization_id=body.organization_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    prometheus_registry.gauge(
        item.name,
        item.value,
        help_text=f"Ingested Amosclaud metric from {item.source}",
        labels=dict(item.labels),
    )
    return _metric_payload(item)


@router.get("/metrics", summary="List recent metric samples")
def list_metrics(
    request: Request,
    name: str | None = Query(default=None, max_length=128),
    organization_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=1_000),
) -> dict[str, Any]:
    _admin_actor(request)
    items = get_monitoring_service().list_metrics(
        name=name,
        organization_id=organization_id,
        limit=limit,
    )
    return {"count": len(items), "metrics": [_metric_payload(item) for item in items]}


@router.post(
    "/deployments/events",
    status_code=status.HTTP_201_CREATED,
    summary="Record deployment lifecycle evidence",
)
def create_deployment_event(
    body: DeploymentEventCreate,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor_id = _ingest_actor(request, authorization)
    try:
        item = get_monitoring_service().record_deployment_event(
            provider=body.provider,
            service=body.service,
            environment=body.environment,
            status=body.status,
            revision=body.revision,
            message=body.message,
            metadata=body.metadata,
            actor_id=actor_id,
            organization_id=body.organization_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    prometheus_registry.counter(
        "amosclaud_deployment_events_total",
        help_text="Recorded deployment lifecycle events",
        labels={
            "provider": item.provider,
            "environment": item.environment,
            "status": item.status.value,
        },
    )
    return _deployment_payload(item)


@router.get("/deployments/events", summary="List deployment lifecycle evidence")
def list_deployment_events(
    request: Request,
    organization_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=1_000),
) -> dict[str, Any]:
    _admin_actor(request)
    items = get_monitoring_service().list_deployment_events(
        organization_id=organization_id,
        limit=limit,
    )
    return {"count": len(items), "events": [_deployment_payload(item) for item in items]}


@router.post(
    "/audit/events",
    status_code=status.HTTP_201_CREATED,
    summary="Record trusted audit evidence",
)
def create_audit_event(
    body: AuditEventCreate,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor_id = _ingest_actor(request, authorization)
    try:
        item = get_monitoring_service().record_audit(
            action=body.action,
            resource_type=body.resource_type,
            resource_id=body.resource_id,
            outcome=body.outcome,
            reason=body.reason,
            metadata=body.metadata,
            actor_id=actor_id,
            organization_id=body.organization_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _audit_payload(item)


@router.get("/audit/events", summary="List recent audit evidence")
def list_audit_events(
    request: Request,
    organization_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=1_000),
) -> dict[str, Any]:
    _admin_actor(request)
    items = get_monitoring_service().list_audit_events(
        organization_id=organization_id,
        limit=limit,
    )
    return {"count": len(items), "events": [_audit_payload(item) for item in items]}
