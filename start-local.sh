#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
APP_ROOT="$ROOT/app"
[[ -d "$APP_ROOT" ]] || APP_ROOT="$ROOT"

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Python 3.11 or newer is required." >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  "$PYTHON" -m venv .venv
fi

VENV_PYTHON="$ROOT/.venv/bin/python"
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -e "$APP_ROOT"

[[ -f .env ]] || cp .env.example .env
mkdir -p data data/repositories data/storage

export AUTH_DB_PATH="${AUTH_DB_PATH:-$ROOT/data/auth.db}"
export REPOSITORY_STORAGE_PATH="${REPOSITORY_STORAGE_PATH:-$ROOT/data/repositories}"
export STORAGE_PATH="${STORAGE_PATH:-$ROOT/data/storage}"
export HOST="${HOST:-127.0.0.1}"
export PORT="${PORT:-8000}"

echo "Amosclaud Agent Server: http://localhost:$PORT"
cd "$ROOT"
exec "$VENV_PYTHON" -m uvicorn amoscloud_ai.main:app --host "$HOST" --port "$PORT"
