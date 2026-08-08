# Amosclaud Telemetry Stack

This directory is the shared observability ingestion and storage layer for the Amosclaud ecosystem. It is additive: existing applications, legacy services, GitHub-native automation, execution nodes, Java pods, pipeline workers, and PipeFail controllers keep their own responsibilities and send telemetry through one OTLP contract.

## Architecture

```text
Amosclaud services / nodes / Java pods / GitHub-native workers
                         |
                  OTLP gRPC/HTTP
                         |
               OpenTelemetry Collector
                    /             \
             metrics               logs + traces
               |                        |
          Prometheus                ClickHouse
```

- **OpenTelemetry SDK / auto-instrumentation** creates traces, metrics, and correlated logs in application runtimes.
- **OpenTelemetry Collector** receives OTLP on ports 4317 and 4318, adds Amosclaud resource identity, applies memory protection, retries delivery, and keeps the ClickHouse delivery queue on persistent storage.
- **Prometheus** is the time-series metrics store.
- **ClickHouse** is the private durable store for logs and traces.

The ClickHouse metrics exporter is intentionally not used because its upstream stability is currently alpha. This keeps Amosclaud metrics on Prometheus while ClickHouse receives the signals for which its OpenTelemetry exporter is beta.

## Start locally or on a private server

Create a strong local password without committing it:

```bash
export CLICKHOUSE_PASSWORD='replace-with-a-strong-secret'
```

Start the stack from this directory:

```bash
docker compose -f docker-compose.telemetry.yml up -d
```

OTLP endpoints are then available only on the host loopback interface:

- gRPC: `http://127.0.0.1:4317`
- HTTP/protobuf: `http://127.0.0.1:4318`
- Prometheus: `http://127.0.0.1:9090`
- ClickHouse HTTP query endpoint: `http://127.0.0.1:8123`

## Connect an Amosclaud Python service

The repository installs the OpenTelemetry Python distro and OTLP exporter. Existing service startup remains unchanged unless telemetry is explicitly enabled.

```bash
export AMOSCLAUD_TELEMETRY_ENABLED=true
export OTEL_SERVICE_NAME=amosclaud-platform
export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_TRACES_EXPORTER=otlp
export OTEL_METRICS_EXPORTER=otlp
export OTEL_LOGS_EXPORTER=otlp
```

Containerized services should use `http://otel-collector:4318` when attached to the same Docker network. Self-hosted nodes on another machine should use the private address of the collector and protect that endpoint with the deployment's network policy or TLS gateway.

## Ecosystem identity

Every service should set `OTEL_SERVICE_NAME` and may add stable resource attributes:

```bash
export OTEL_RESOURCE_ATTRIBUTES='amosclaud.pipeline.id=pipe_123,amosclaud.node.id=node_01,amosclaud.runtime=java-pod'
```

Do not put API keys, session cookies, authorization headers, source code, prompts containing secrets, or customer credentials into telemetry attributes.

Recommended service names include:

- `amosclaud-platform`
- `amosclaud-agent`
- `amosclaud-ai-gateway`
- `amosclaud-pipeline-orchestrator`
- `amosclaud-pipefail`
- `amosclaud-node-proposer`
- `amosclaud-java-pod`
- `amosclaud-github-native`
- legacy service names prefixed with `amosclaud-legacy-`

## Retention

Defaults are deliberately bounded for a self-hosted first deployment:

- ClickHouse logs/traces: `168h` (7 days), controlled by `AMOSCLAUD_TELEMETRY_TTL`.
- Prometheus metrics: `15d`, controlled by `AMOSCLAUD_PROMETHEUS_RETENTION`.

Increase retention only after sizing disk capacity and backup policy.

## Failure behavior

Telemetry is not allowed to become a dependency that stops Amosclaud from operating. If telemetry is disabled, existing services run exactly as before. If a collector or backend becomes unavailable, application execution continues; the collector retries and its ClickHouse exporter uses a persistent queue. PipeFail records application and pipeline failures independently of whether the observability backend is currently reachable.
