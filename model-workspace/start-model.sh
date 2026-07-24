#!/usr/bin/env sh
set -eu

MODEL_HOME="${AMOSCLAUD_MODEL_HOME:-/model}"
MODEL_HOST="${AMOSCLAUD_MODEL_HOST:-0.0.0.0}"
MODEL_PORT="${AMOSCLAUD_MODEL_PORT:-8091}"
BOOTSTRAP_DIR="${AMOSCLAUD_MODEL_BOOTSTRAP_DIR:-/app/bootstrap}"
AUTO_TRAIN="${AMOSCLAUD_MODEL_AUTO_TRAIN:-true}"

case "$MODEL_PORT" in
  ''|*[!0-9]*) echo "[model] AMOSCLAUD_MODEL_PORT must be numeric" >&2; exit 2 ;;
esac

mkdir -p "$MODEL_HOME" "$MODEL_HOME/checkpoints" "$MODEL_HOME/logs" "$MODEL_HOME/training/jobs"

python - <<'PY'
import json
import os
from pathlib import Path

metadata_path = Path('/app/model_metadata.json')
metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
required = {'model_id', 'display_name', 'version', 'owner', 'capabilities', 'interfaces', 'data_policy'}
missing = sorted(required - metadata.keys())
if missing:
    raise SystemExit(f"[model] metadata is missing: {', '.join(missing)}")
if metadata.get('owner') != 'amosclaud':
    raise SystemExit('[model] metadata owner must be amosclaud')

home = Path(os.environ.get('AMOSCLAUD_MODEL_HOME', '/model'))
probe = home / '.write-test'
probe.write_text('ok', encoding='utf-8')
probe.unlink()
print(f"[model] workspace ready: {home}")
print(f"[model] identity: {metadata['model_id']} v{metadata['version']}")
PY

amosclaud-model init

if [ ! -f "$MODEL_HOME/checkpoints/current.json" ]; then
  if [ "$AUTO_TRAIN" != "true" ]; then
    echo "[model] no checkpoint found and automatic bootstrap training is disabled" >&2
    exit 1
  fi
  if [ ! -d "$BOOTSTRAP_DIR" ] || [ -z "$(find "$BOOTSTRAP_DIR" -type f -print -quit 2>/dev/null)" ]; then
    echo "[model] no approved bootstrap dataset is available at $BOOTSTRAP_DIR" >&2
    exit 1
  fi
  echo "[model] importing approved project-owned bootstrap dataset"
  amosclaud-model import "$BOOTSTRAP_DIR" --license project-owned
  amosclaud-model license-audit
  amosclaud-model train
  amosclaud-model evaluate
fi

exec amosclaud-model serve --host "$MODEL_HOST" --port "$MODEL_PORT"
