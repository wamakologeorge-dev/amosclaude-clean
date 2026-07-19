#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd "$(dirname "$0")" && pwd)"
app="$root"
[[ -f "$root/app/amoscloud_ai/virtual_memory.py" ]] && app="$root/app"
cd "$app"

python3 -m amoscloud_ai.virtual_memory status
if [[ "${1:-}" != "--apply" ]]; then
  echo "No changes made. Run sudo ./install-virtual-memory.sh --apply to accept the recommendation."
  exit 0
fi
[[ "$(id -u)" -eq 0 ]] || { echo "Use sudo when applying virtual memory." >&2; exit 1; }
python3 -m amoscloud_ai.virtual_memory apply --yes
