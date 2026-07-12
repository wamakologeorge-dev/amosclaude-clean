#!/usr/bin/env bash
set -Eeuo pipefail

# Amosclaud production entrypoint.
# Railway supplies PORT automatically; local runs default to 8000.
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
WORKERS="${WORKERS:-1}"

# Hosted production must explicitly point authentication and repositories at
# a mounted persistent volume. Local development may continue using ./data.
if [[ -n "${RAILWAY_ENVIRONMENT:-}" || -n "${RENDER:-}" || -n "${RENDER_SERVICE_ID:-}" || "${ENVIRONMENT:-}" == "production" || "${APP_ENV:-}" == "production" ]]; then
  : "${AUTH_DB_PATH:?AUTH_DB_PATH must point to a persistent database file, for example /data/auth.db}"
  : "${REPOSITORY_STORAGE_PATH:?REPOSITORY_STORAGE_PATH must point to persistent storage, for example /data/repositories}"
fi

DATA_DIR="${DATA_DIR:-$(dirname "${AUTH_DB_PATH:-data/auth.db}")}"
mkdir -p "$DATA_DIR" "${REPOSITORY_STORAGE_PATH:-data/repositories}"

python scripts/check_persistence.py

exec python -m uvicorn amoscloud_ai.main:app \
  --host "$HOST" \
  --port "$PORT" \
  --workers "$WORKERS" \
  --proxy-headers \
  --forwarded-allow-ips="*"
