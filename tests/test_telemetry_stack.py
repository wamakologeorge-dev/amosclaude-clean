from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TELEMETRY = ROOT / "Infrastructure" / "telemetry"


def test_collector_routes_all_three_signals_to_private_backends() -> None:
    config = yaml.safe_load((TELEMETRY / "otel-collector.yaml").read_text(encoding="utf-8"))
    pipelines = config["service"]["pipelines"]

    assert set(pipelines) == {"traces", "metrics", "logs"}
    assert pipelines["metrics"]["exporters"] == ["prometheus"]
    assert pipelines["traces"]["exporters"] == ["clickhouse"]
    assert pipelines["logs"]["exporters"] == ["clickhouse"]
    assert config["receivers"]["otlp"]["protocols"]["grpc"]["endpoint"].endswith(":4317")
    assert config["receivers"]["otlp"]["protocols"]["http"]["endpoint"].endswith(":4318")


def test_clickhouse_delivery_is_bounded_retryable_and_persistent() -> None:
    config = yaml.safe_load((TELEMETRY / "otel-collector.yaml").read_text(encoding="utf-8"))
    exporter = config["exporters"]["clickhouse"]

    assert exporter["ttl"] == "${env:AMOSCLAUD_TELEMETRY_TTL:-168h}"
    assert exporter["sending_queue"]["storage"] == "file_storage/telemetry"
    assert exporter["sending_queue"]["batch"]["max_size"] == 5000
    assert exporter["retry_on_failure"]["enabled"] is True
    assert exporter["retry_on_failure"]["max_elapsed_time"] == "300s"


def test_telemetry_stack_keeps_datastores_private_to_host() -> None:
    compose = yaml.safe_load(
        (TELEMETRY / "docker-compose.telemetry.yml").read_text(encoding="utf-8")
    )

    assert compose["services"]["otel-collector"]["ports"] == [
        "127.0.0.1:4317:4317",
        "127.0.0.1:4318:4318",
        "127.0.0.1:13133:13133",
    ]
    assert compose["services"]["prometheus"]["ports"] == ["127.0.0.1:9090:9090"]
    assert compose["services"]["clickhouse"]["ports"] == ["127.0.0.1:8123:8123"]


def test_runtime_wrapper_preserves_legacy_startup_when_disabled() -> None:
    wrapper = (ROOT / "docker" / "otel-exec.sh").read_text(encoding="utf-8")
    production = (ROOT / "docker" / "production-entrypoint.sh").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert 'AMOSCLAUD_TELEMETRY_ENABLED:-false' in wrapper
    assert 'exec "$@"' in wrapper
    assert "opentelemetry-instrument" in wrapper
    assert "exec /app/docker/otel-exec.sh uvicorn amoscloud_ai.main:app" in production
    assert "${PORT:-8000}" in dockerfile


def test_python_runtime_has_pinned_otel_components() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "opentelemetry-distro==0.65b0" in requirements
    assert "opentelemetry-exporter-otlp==1.44.0" in requirements
    assert "opentelemetry-instrumentation-fastapi==0.65b0" in requirements
    assert "opentelemetry-instrumentation-logging==0.65b0" in requirements
