"""SQLite persistence and concrete health probes for monitoring services."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Sequence

from .domain import (
    AuditEvent,
    AuditOutcome,
    DeploymentEvent,
    DeploymentStatus,
    HealthCheckResult,
    HealthStatus,
    MetricSample,
)


class SQLiteMonitoringRepository:
    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 5000")
        return db

    def initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS monitoring_metrics (
                    id TEXT PRIMARY KEY,
                    organization_id INTEGER,
                    name TEXT NOT NULL,
                    value REAL NOT NULL,
                    unit TEXT NOT NULL,
                    source TEXT NOT NULL,
                    labels_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_monitoring_metrics_recent
                    ON monitoring_metrics(recorded_at DESC);
                CREATE INDEX IF NOT EXISTS idx_monitoring_metrics_name_recent
                    ON monitoring_metrics(name, recorded_at DESC);

                CREATE TABLE IF NOT EXISTS monitoring_deployment_events (
                    id TEXT PRIMARY KEY,
                    organization_id INTEGER,
                    provider TEXT NOT NULL,
                    service TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    status TEXT NOT NULL,
                    revision TEXT,
                    message TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_monitoring_deployments_recent
                    ON monitoring_deployment_events(created_at DESC);

                CREATE TABLE IF NOT EXISTS monitoring_audit_events (
                    id TEXT PRIMARY KEY,
                    actor_id INTEGER,
                    organization_id INTEGER,
                    action TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT,
                    outcome TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_monitoring_audit_recent
                    ON monitoring_audit_events(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_monitoring_audit_actor_recent
                    ON monitoring_audit_events(actor_id, created_at DESC);
                """
            )
            db.commit()

    def append_metric(self, sample: MetricSample) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO monitoring_metrics
                (id,organization_id,name,value,unit,source,labels_json,recorded_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (
                    sample.id,
                    sample.organization_id,
                    sample.name,
                    sample.value,
                    sample.unit,
                    sample.source,
                    json.dumps(dict(sample.labels), sort_keys=True, separators=(",", ":")),
                    sample.recorded_at.isoformat(),
                ),
            )
            db.commit()

    def list_metrics(
        self, *, name: str | None, organization_id: int | None, limit: int
    ) -> Sequence[MetricSample]:
        clauses: list[str] = []
        values: list[object] = []
        if name:
            clauses.append("name = ?")
            values.append(name)
        if organization_id is not None:
            clauses.append("organization_id = ?")
            values.append(organization_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(limit)
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM monitoring_metrics{where} ORDER BY recorded_at DESC LIMIT ?",
                values,
            ).fetchall()
        return [
            MetricSample(
                id=row["id"],
                organization_id=row["organization_id"],
                name=row["name"],
                value=float(row["value"]),
                unit=row["unit"],
                source=row["source"],
                labels=json.loads(row["labels_json"] or "{}"),
                recorded_at=datetime.fromisoformat(row["recorded_at"]),
            )
            for row in rows
        ]

    def append_deployment_event(self, event: DeploymentEvent) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO monitoring_deployment_events
                (id,organization_id,provider,service,environment,status,revision,message,metadata_json,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    event.id,
                    event.organization_id,
                    event.provider,
                    event.service,
                    event.environment,
                    event.status.value,
                    event.revision,
                    event.message,
                    json.dumps(dict(event.metadata), sort_keys=True, separators=(",", ":")),
                    event.created_at.isoformat(),
                ),
            )
            db.commit()

    def list_deployment_events(
        self, *, organization_id: int | None, limit: int
    ) -> Sequence[DeploymentEvent]:
        where = " WHERE organization_id = ?" if organization_id is not None else ""
        values: list[object] = [organization_id, limit] if organization_id is not None else [limit]
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM monitoring_deployment_events{where} ORDER BY created_at DESC LIMIT ?",
                values,
            ).fetchall()
        return [
            DeploymentEvent(
                id=row["id"],
                organization_id=row["organization_id"],
                provider=row["provider"],
                service=row["service"],
                environment=row["environment"],
                status=DeploymentStatus(row["status"]),
                revision=row["revision"],
                message=row["message"],
                metadata=json.loads(row["metadata_json"] or "{}"),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def append_audit_event(self, event: AuditEvent) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO monitoring_audit_events
                (id,actor_id,organization_id,action,resource_type,resource_id,outcome,reason,metadata_json,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    event.id,
                    event.actor_id,
                    event.organization_id,
                    event.action,
                    event.resource_type,
                    event.resource_id,
                    event.outcome.value,
                    event.reason,
                    json.dumps(dict(event.metadata), sort_keys=True, separators=(",", ":")),
                    event.created_at.isoformat(),
                ),
            )
            db.commit()

    def list_audit_events(
        self, *, organization_id: int | None, limit: int
    ) -> Sequence[AuditEvent]:
        where = " WHERE organization_id = ?" if organization_id is not None else ""
        values: list[object] = [organization_id, limit] if organization_id is not None else [limit]
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM monitoring_audit_events{where} ORDER BY created_at DESC LIMIT ?",
                values,
            ).fetchall()
        return [
            AuditEvent(
                id=row["id"],
                actor_id=row["actor_id"],
                organization_id=row["organization_id"],
                action=row["action"],
                resource_type=row["resource_type"],
                resource_id=row["resource_id"],
                outcome=AuditOutcome(row["outcome"]),
                reason=row["reason"],
                metadata=json.loads(row["metadata_json"] or "{}"),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]


class PathHealthProbe:
    def __init__(self, name: str, path: Path, *, expect_file: bool = False) -> None:
        self.name = name
        self.path = Path(path).expanduser()
        self.expect_file = expect_file

    def run(self) -> HealthCheckResult:
        started = time.monotonic()
        exists = self.path.is_file() if self.expect_file else self.path.is_dir()
        if not exists:
            return HealthCheckResult.create(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                summary="Required path is unavailable",
                latency_ms=(time.monotonic() - started) * 1000,
                details={"kind": "file" if self.expect_file else "directory"},
            )
        target = self.path.parent if self.expect_file else self.path
        usage = shutil.disk_usage(target)
        free_ratio = usage.free / usage.total if usage.total else 0.0
        status = HealthStatus.DEGRADED if free_ratio < 0.10 else HealthStatus.HEALTHY
        return HealthCheckResult.create(
            name=self.name,
            status=status,
            summary="Path is available" if status == HealthStatus.HEALTHY else "Path has low free space",
            latency_ms=(time.monotonic() - started) * 1000,
            details={
                "free_bytes": usage.free,
                "total_bytes": usage.total,
                "free_ratio": round(free_ratio, 4),
            },
        )


class HttpHealthProbe:
    def __init__(self, name: str, url: str, *, timeout: float = 2.0) -> None:
        self.name = name
        self.url = url
        self.timeout = timeout

    def run(self) -> HealthCheckResult:
        started = time.monotonic()
        try:
            with urllib.request.urlopen(self.url, timeout=self.timeout) as response:
                status_code = int(response.status)
            status = HealthStatus.HEALTHY if 200 <= status_code < 400 else HealthStatus.DEGRADED
            summary = f"Service returned HTTP {status_code}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return HealthCheckResult.create(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                summary="Service health request failed",
                latency_ms=(time.monotonic() - started) * 1000,
                details={"error_type": type(exc).__name__},
            )
        return HealthCheckResult.create(
            name=self.name,
            status=status,
            summary=summary,
            latency_ms=(time.monotonic() - started) * 1000,
            details={"status_code": status_code},
        )


def build_default_probes() -> tuple[PathHealthProbe | HttpHealthProbe, ...]:
    probes: list[PathHealthProbe | HttpHealthProbe] = [
        PathHealthProbe(
            "authentication_database",
            Path(os.getenv("AUTH_DB_PATH", "data/auth.db")),
            expect_file=True,
        ),
        PathHealthProbe(
            "repository_storage",
            Path(os.getenv("REPOSITORY_STORAGE_PATH", "data/repositories")),
        ),
        PathHealthProbe(
            "object_storage",
            Path(os.getenv("STORAGE_PATH", "data/storage")),
        ),
    ]
    metrics_url = os.getenv("AMOSCLAUD_METRICS_HEALTH_URL", "").strip()
    if metrics_url:
        probes.append(HttpHealthProbe("metrics_service", metrics_url))
    return tuple(probes)
