#!/usr/bin/env bash
set -euo pipefail

umask 0027
cd /workspace
exec "$@"
