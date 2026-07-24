#!/usr/bin/env bash
set -Eeuo pipefail

# Canonical Amosclaud Autonomous production entrypoint.
# This launcher performs storage and import preflight checks, then starts the
# single platform application exported by amoscloud_ai.main.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
WORKERS="${WORKERS:-1}"
APP_MODULE="${AMOSCLAUD_APP_MODULE:-amoscloud_ai.main:app}"

case "$PORT" in
  ''|*[!0-9]*) echo "[startup] ERROR: PORT must be a number" >&2; exit 2 ;;
esac
case "$WORKERS" in
  ''|*[!0-9]*) echo "[startup] ERROR: WORKERS must be a positive number" >&2; exit 2 ;;
esac
if (( PORT < 1 || PORT > 65535 )); then
  echo "[startup] ERROR: PORT must be between 1 and 65535" >&2
  exit 2
fi
if (( WORKERS < 1 )); then
  echo "[startup] ERROR: WORKERS must be at least 1" >&2
  exit 2
fi

# Hosted production must explicitly use mounted persistent storage. Local
# development remains compatible with repository-local ./data paths.
HOSTED_PRODUCTION=false
if [[ -n "${RAILWAY_ENVIRONMENT:-}" || -n "${RENDER:-}" || -n "${RENDER_SERVICE_ID:-}" || "${ENVIRONMENT:-}" =~ ^(production|prod)$ || "${APP_ENV:-}" =~ ^(production|prod)$ ]]; then
  HOSTED_PRODUCTION=true
  : "${AUTH_DB_PATH:?AUTH_DB_PATH must point to a persistent database file, for example /data/auth/auth.db}"
  : "${REPOSITORY_STORAGE_PATH:?REPOSITORY_STORAGE_PATH must point to persistent storage, for example /data/repositories}"
fi

export AUTH_DB_PATH="${AUTH_DB_PATH:-data/auth.db}"
export REPOSITORY_STORAGE_PATH="${REPOSITORY_STORAGE_PATH:-data/repositories}"
export AMOSCLAUD_STORAGE_PATH="${AMOSCLAUD_STORAGE_PATH:-data/platform}"
export AMOSCLAUD_MODEL_HOME="${AMOSCLAUD_MODEL_HOME:-data/model}"
export REQUIRE_PERSISTENT_STORAGE="${REQUIRE_PERSISTENT_STORAGE:-$HOSTED_PRODUCTION}"

mkdir -p \
  "$(dirname "$AUTH_DB_PATH")" \
  "$REPOSITORY_STORAGE_PATH" \
  "$AMOSCLAUD_STORAGE_PATH" \
  "$AMOSCLAUD_MODEL_HOME"

python "$PROJECT_ROOT/scripts/check_persistence.py"

# Fail before binding the public port if the canonical application cannot be
# imported. This also prevents deployment scripts from silently starting a
# legacy or duplicate FastAPI app.
python - <<'PY'
from amoscloud_ai.main import app

paths = {getattr(route, "path", "") for route in app.routes}
required = {"/health", "/api/v1/agent/run"}
missing = sorted(required - paths)
if missing:
    raise SystemExit(f"[startup] canonical app is missing required routes: {missing}")
print(f"[startup] canonical Amosclaud app ready with {len(paths)} routes")
PY

exec python -m uvicorn "$APP_MODULE" \
  --host "$HOST" \
  --port "$PORT" \
  --workers "$WORKERS" \
  --proxy-headers \
  --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-*}"
