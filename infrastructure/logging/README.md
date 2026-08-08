# Amosclaud self-hosted logging stack

## Start

```bash
cd infrastructure/logging
export POSTGRES_PASSWORD='replace-me'
export AMOSCLAUD_LOGGING_API_KEYS='developer-key:tenant-development'
docker compose up --build
```

Services:
- ingestion and live stream: `http://localhost:8080`
- query API: `http://localhost:8081`
- dashboard: `http://localhost:8082`
- MinIO console: `http://localhost:9001`
- Prometheus: `http://localhost:9090`

Fixee integration is proposal-only. A log event cannot commit, push, deploy, or modify a repository. Any later execution must pass Amosclaud's separate approval and verification controls.
