#!/usr/bin/env sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"
PYTHON_BIN=${PYTHON_BIN:-python3}
exec "$PYTHON_BIN" -m amoscloud_ai.quickcheck_cli "$@"
