# Monitoring Services and Audit Logs

This module is the first Phase 4 implementation from the Autonomous Engineering Workforce roadmap. It adds durable health evidence, metric ingestion, deployment lifecycle records, and audit events without coupling the core use cases to FastAPI or SQLite.

## Architecture

```text
amoscloud_ai/monitoring/domain.py          pure entities and value rules
amoscloud_ai/monitoring/ports.py           repository and probe protocols
amoscloud_ai/monitoring/application.py     monitoring and audit use cases
amoscloud_ai/monitoring/infrastructure.py  SQLite repository and concrete probes
amoscloud_ai/api/routes/monitoring.py      authenticated FastAPI adapter
```

The domain and application modules import no web framework, database library, or Amosclaud route. Infrastructure implements the repository and probe ports. The HTTP adapter handles authentication, validation, and response presentation.

## API

All routes are mounted under `/api/v1/monitoring`.

- `GET /health` — administrator-only current platform checks.
- `POST /metrics` — administrator session or monitoring-ingest bearer token.
- `GET /metrics` — administrator-only recent metric samples.
- `POST /deployments/events` — trusted deployment lifecycle ingestion.
- `GET /deployments/events` — administrator-only deployment evidence.
- `POST /audit/events` — trusted audit-evidence ingestion.
- `GET /audit/events` — administrator-only audit history.

Machine ingestion uses:

```text
Authorization: Bearer <AMOSCLAUD_MONITORING_INGEST_TOKEN>
```

Do not put this token in repository files, project containers, browser JavaScript, deployment logs, or agent context.

## Default health probes

The initial health collector verifies:

- the authentication database exists;
- repository storage is available and has sufficient free space;
- object storage is available and has sufficient free space;
- the standalone metrics service is reachable when `AMOSCLAUD_METRICS_HEALTH_URL` is configured.

A missing required path is unhealthy. Less than 10% free disk space is degraded. Probe exceptions are converted into truthful unhealthy evidence; the endpoint never fabricates a healthy result.

## Audit safety

Audit and deployment metadata is recursively bounded and redacts keys containing terms such as `authorization`, `cookie`, `password`, `secret`, `token`, `api_key`, and `private_key`. Audit records contain identifiers and evidence only, never credential values.

## Persistence

The default adapter uses `AMOSCLAUD_MONITORING_DB_PATH` and creates three idempotent SQLite tables:

- `monitoring_metrics`
- `monitoring_deployment_events`
- `monitoring_audit_events`

The application depends only on the `MonitoringRepository` protocol. A future SQLAlchemy/MySQL or PostgreSQL adapter can replace SQLite without changing domain entities, use cases, or HTTP contracts.

## Verification

Run the focused suite:

```bash
pytest -q tests/test_monitoring_services.py
```

The tests cover aggregate health status, persistence, secret redaction, ingest-token authorization, administrator reads, and route contracts.
