#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env.production ]]; then
  echo "Missing .env.production. Copy .env.production.example and set real secrets." >&2
  exit 1
fi

git fetch origin main
git reset --hard origin/main

docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
docker compose -f docker-compose.prod.yml ps

curl --fail --retry 12 --retry-delay 5 https://amosclaud.com/health
