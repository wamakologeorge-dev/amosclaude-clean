#!/usr/bin/env bash
set -euo pipefail

umask 0027
mkdir -p /workspace

if [[ ! -f /workspace/.amosclaud-workspace ]]; then
  cat > /workspace/.amosclaud-workspace <<'EOF'
This directory is persistent Amosclaud workspace storage.
The container may stop, but project files and Git history remain here.
EOF
fi

exec "$@"
