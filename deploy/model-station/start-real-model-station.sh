#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: Docker is required on the model-station machine."
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: Docker Compose v2 is required."
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created deploy/model-station/.env from .env.example."
  echo "Set AMOSCLAUD_MODEL_TOKEN to a private random value, then run this command again."
  exit 2
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

: "${AMOSCLAUD_MODEL_NAME:=qwen2.5-coder:7b}"
: "${AMOSCLAUD_MODEL_PORT:=8090}"

if [[ -z "${AMOSCLAUD_MODEL_TOKEN:-}" ]]; then
  echo "ERROR: AMOSCLAUD_MODEL_TOKEN is missing in deploy/model-station/.env"
  exit 3
fi

echo "Starting Amosclaud real model station with ${AMOSCLAUD_MODEL_NAME}..."
docker compose down --remove-orphans
docker compose pull ollama model-bootstrap
docker compose up -d --build

echo "Waiting for the model station to complete a real inference health check..."
for attempt in $(seq 1 60); do
  status="$(docker compose ps --format json 2>/dev/null || true)"
  if curl --fail --silent --show-error \
    --max-time 330 \
    -H "Authorization: Bearer ${AMOSCLAUD_MODEL_TOKEN}" \
    "http://127.0.0.1:${AMOSCLAUD_MODEL_PORT}/ready" \
    | python -c 'import json,sys; data=json.load(sys.stdin); raise SystemExit(0 if data.get("ready") is True else 1)' \
    2>/dev/null; then
    echo "SUCCESS: Amosclaud model station is ready at http://127.0.0.1:${AMOSCLAUD_MODEL_PORT}"
    echo "Configure the Amosclaud application with:"
    echo "AMOSCLAUD_MODEL_URL=http://<MODEL-STATION-HOST>:${AMOSCLAUD_MODEL_PORT}"
    echo "AMOSCLAUD_MODEL_TOKEN=<same private token>"
    exit 0
  fi
  echo "Attempt ${attempt}/60: model is still loading..."
  sleep 10
done

echo "ERROR: model station did not become ready."
docker compose ps
docker compose logs --tail=200 ollama model-bootstrap model-station station-runner
exit 4
