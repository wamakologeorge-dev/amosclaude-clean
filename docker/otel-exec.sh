#!/bin/sh
set -eu

# Telemetry is opt-in and fail-open at the application boundary. Existing and
# legacy services keep their normal command when telemetry is disabled.
if [ "${AMOSCLAUD_TELEMETRY_ENABLED:-false}" = "true" ]; then
    if ! command -v opentelemetry-instrument >/dev/null 2>&1; then
        echo "Amosclaud telemetry requested but opentelemetry-instrument is unavailable; starting service without instrumentation." >&2
        exec "$@"
    fi

    : "${OTEL_SERVICE_NAME:=amosclaud-platform}"
    : "${OTEL_TRACES_EXPORTER:=otlp}"
    : "${OTEL_METRICS_EXPORTER:=otlp}"
    : "${OTEL_LOGS_EXPORTER:=otlp}"
    : "${OTEL_EXPORTER_OTLP_PROTOCOL:=http/protobuf}"
    export OTEL_SERVICE_NAME OTEL_TRACES_EXPORTER OTEL_METRICS_EXPORTER OTEL_LOGS_EXPORTER
    export OTEL_EXPORTER_OTLP_PROTOCOL

    exec opentelemetry-instrument \
        --traces_exporter "$OTEL_TRACES_EXPORTER" \
        --metrics_exporter "$OTEL_METRICS_EXPORTER" \
        --logs_exporter "$OTEL_LOGS_EXPORTER" \
        "$@"
fi

exec "$@"
