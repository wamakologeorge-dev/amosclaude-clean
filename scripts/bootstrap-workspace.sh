#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p \
  data/repositories \
  data/model/checkpoints/versions \
  data/model/logs/service \
  data/model/training/jobs \
  .cache

python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .

if [ ! -f .env ]; then
  cp .env.workspace.example .env
  echo "Created .env from .env.workspace.example"
fi

python -m compileall -q \
  amoscloud_ai \
  agents \
  amomodel \
  amosclaud_agent_sdk \
  amosclaud_metrics \
  amosclaud_platform \
  api_key_manager \
  app \
  database \
  repository

python - <<'PY'
from amoscloud_ai.main import app

paths = {getattr(route, "path", "") for route in app.routes}
assert "/health" in paths, "Unified Amosclaud application did not register /health"
print(f"Validated Amosclaud application with {len(paths)} registered paths.")
PY

# Development credentials are intentionally not embedded here. The doctor command
# reports missing service secrets and optional dependencies without exposing values.
python -m amosclaud_platform doctor || true

echo
printf '%s\n' "Amosclaud Platform Workspace is ready."
printf '%s\n' "Start the platform with: python -m amosclaud_platform start"
printf '%s\n' "Check readiness with: python -m amosclaud_platform doctor"
printf '%s\n' "Open: http://localhost:8000"
