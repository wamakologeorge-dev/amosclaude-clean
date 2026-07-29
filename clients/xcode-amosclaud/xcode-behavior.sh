#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-plan}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASK="${AMOSCLAUD_TASK:-}"

if [[ -z "$TASK" ]] && command -v osascript >/dev/null 2>&1; then
  TASK="$(osascript <<'APPLESCRIPT'
try
  text returned of (display dialog "What should Amosclaud do?" default answer "" with title "Amosclaud Autonomous")
on error
  return ""
end try
APPLESCRIPT
)"
fi

if [[ -z "$TASK" ]]; then
  echo "No Amosclaud task was supplied." >&2
  exit 1
fi

ARGS=("$MODE" "--task" "$TASK")

if [[ -n "${AMOSCLAUD_REPOSITORY:-}" ]]; then
  ARGS+=("--repository" "$AMOSCLAUD_REPOSITORY")
fi

if [[ -n "${AMOSCLAUD_BRANCH:-}" ]]; then
  ARGS+=("--branch" "$AMOSCLAUD_BRANCH")
fi

ACTIVE_FILE="${SCRIPT_INPUT_FILE_0:-${AMOSCLAUD_ACTIVE_FILE:-}}"
if [[ -n "$ACTIVE_FILE" && -n "${SRCROOT:-}" && "$ACTIVE_FILE" == "$SRCROOT"/* ]]; then
  ARGS+=("--file" "${ACTIVE_FILE#"$SRCROOT"/}")
fi

if [[ -n "${AMOSCLAUD_LANGUAGE:-}" ]]; then
  ARGS+=("--language" "$AMOSCLAUD_LANGUAGE")
fi

if [[ -n "${AMOSCLAUD_SELECTION_FILE:-}" ]]; then
  ARGS+=("--selection-file" "$AMOSCLAUD_SELECTION_FILE")
fi

if [[ -n "${AMOSCLAUD_AGENT:-}" ]]; then
  ARGS+=("--agent" "$AMOSCLAUD_AGENT")
fi

exec swift run --package-path "$SCRIPT_DIR" amosclaud-xcode "${ARGS[@]}"
