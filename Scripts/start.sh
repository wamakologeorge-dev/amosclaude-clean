#!/usr/bin/env bash
set -Eeuo pipefail

# Amosclaud production entrypoint.
# Railway supplies PORT automatically; local runs default to 8000.
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
WORKERS="${WORKERS:-1}"

mkdir -p "${DATA_DIR:-data}"

exec python -m uvicorn amoscloud_ai.main:app \
  --host "$HOST" \
  --port "$PORT" \
  --workers "$WORKERS" \
  --proxy-headers \
  --forwarded-allow-ips="*"
