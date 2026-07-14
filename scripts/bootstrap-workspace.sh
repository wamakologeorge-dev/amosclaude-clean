#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p data repositories .cache

python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.workspace.example .env
  echo "Created .env from .env.workspace.example"
fi

python -m compileall -q amoscloud_ai
python -m pytest tests/test_server.py -q

echo
printf '%s\n' "Amosclaud Workspace is ready."
printf '%s\n' "Start the app with: make dev"
printf '%s\n' "Open: http://localhost:8000"
