# Amosclaud Metrics Server and SSY

The Metrics Server is the single observability endpoint for Amosclaud. It combines bounded
HTTP request metrics from the application with live probes and read-only operational counts.

It monitors:

- Amosclaud API availability, latency, request counts, status codes, and cumulative duration
- native model availability and probe latency
- users and active sessions
- queued, running, completed, and failed routed tasks
- active Server Stations
- webhook delivery failures
- host load, memory, disk, and uptime

Endpoints:

- `/health` — unprotected container health check
- `/metrics` — Prometheus exposition
- `/v1/summary` — protected JSON snapshot
- `/v1/ssy` — Amosclaud System Service Yard status
- `/v1/alerts` — active availability and resource alerts
- `/v1/history` — retained metric snapshots for charts and incident review

Run locally with `docker compose -f Infrastructure/docker-compose.yml up --build`. The metrics
port binds to `127.0.0.1:9090`, not every network interface. In production,
`AMOSCLAUD_METRICS_TOKEN` is mandatory and requests use `Authorization: Bearer <token>`.

The collector opens the account database in SQLite read-only mode and never exports emails,
object identifiers, prompts, repository names, tokens, or other high-cardinality/private data.
Snapshots are sampled in the background and retained for seven days by default. Configure
`AMOSCLAUD_METRICS_SAMPLE_SECONDS`, `AMOSCLAUD_METRICS_RETENTION_DAYS`, and
`AMOSCLAUD_METRICS_DB` to change that policy.
