#!/bin/sh
set -eu

load_secret() {
    name="$1"
    file_path="$2"
    requirement="${3:-required}"

    current_value="$(printenv "$name" 2>/dev/null || true)"
    if [ -n "$file_path" ] && [ -r "$file_path" ]; then
        value="$(cat "$file_path")"
        if [ -n "$value" ]; then
            export "$name=$value"
            return 0
        fi
    fi

    if [ "$requirement" = "required" ] && [ -z "$current_value" ]; then
        echo "Required production secret $name is missing or empty." >&2
        exit 1
    fi
}

load_secret POSTGRES_PASSWORD "${POSTGRES_PASSWORD_FILE:-}" required
load_secret REDIS_PASSWORD "${REDIS_PASSWORD_FILE:-}" required
load_secret SECRET_KEY "${SECRET_KEY_FILE:-}" required
load_secret AMOSCLAUD_MASTER_KEY "${AMOSCLAUD_MASTER_KEY_FILE:-}" required
load_secret AMOSCLAUD_METRICS_TOKEN "${AMOSCLAUD_METRICS_TOKEN_FILE:-}" required
load_secret GITHUB_TOKEN_ENCRYPTION_KEY "${GITHUB_TOKEN_ENCRYPTION_KEY_FILE:-}" required

load_secret AMOSCLAUD_DASHBOARD_KEY "${AMOSCLAUD_DASHBOARD_KEY_FILE:-}" optional
load_secret AMOSCLAUD_BYTE_BUS_SECRET "${AMOSCLAUD_BYTE_BUS_SECRET_FILE:-}" optional
load_secret AMOSCLAUD_PREVIEW_SERVICE_KEY "${AMOSCLAUD_PREVIEW_SERVICE_KEY_FILE:-}" optional
load_secret AMOSCLAUD_API_KEY "${AMOSCLAUD_API_KEY_FILE:-}" optional
load_secret GITHUB_CLIENT_SECRET "${GITHUB_CLIENT_SECRET_FILE:-}" optional
load_secret AMOSCLAUD_MODEL_TOKEN "${AMOSCLAUD_MODEL_TOKEN_FILE:-}" optional
load_secret STRIPE_SECRET_KEY "${STRIPE_SECRET_KEY_FILE:-}" optional
load_secret STRIPE_WEBHOOK_SECRET "${STRIPE_WEBHOOK_SECRET_FILE:-}" optional

POSTGRES_PASSWORD_ENCODED="$(python - <<'PY'
import os
from urllib.parse import quote

print(quote(os.environ["POSTGRES_PASSWORD"], safe=""))
PY
)"
REDIS_PASSWORD_ENCODED="$(python - <<'PY'
import os
from urllib.parse import quote

print(quote(os.environ["REDIS_PASSWORD"], safe=""))
PY
)"

POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-amosclaud_db}"
POSTGRES_USER="${POSTGRES_USER:-amosclaud}"
REDIS_HOST="${REDIS_HOST:-redis}"
REDIS_PORT="${REDIS_PORT:-6379}"

export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD_ENCODED}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}}"
export AMOSCLAUD_PLATFORM_DATABASE_URL="${AMOSCLAUD_PLATFORM_DATABASE_URL:-$DATABASE_URL}"
export REDIS_URL="${REDIS_URL:-redis://:${REDIS_PASSWORD_ENCODED}@${REDIS_HOST}:${REDIS_PORT}/0}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-$REDIS_URL}"
export CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-$REDIS_URL}"

mkdir -p \
    "${DATA_DIR:-/data}" \
    "${REPOSITORY_STORAGE_PATH:-/data/repositories}" \
    "${STORAGE_PATH:-/data/storage}" \
    "${AMOSCLAUD_DASHBOARD_DATA:-/data/dashboard}" \
    "${AMOSCLAUD_PREVIEW_DATA:-/data/previews}"

exec uvicorn amoscloud_ai.main:app \
    --host "${HOST:-0.0.0.0}" \
    --port "${PORT:-8000}" \
    --workers "${WORKERS:-1}" \
    --proxy-headers \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}"
