#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd "$(dirname "$0")" && pwd)"
app="$root"
[[ -f "$root/app/docker-compose.selfhost.yml" ]] && app="$root/app"
cd "$root"
export PYTHONPATH="$app${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m amoscloud_ai.workspace_control "${1:-doctor}" "${@:2}"
