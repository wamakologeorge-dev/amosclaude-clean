#!/usr/bin/env bash
set -euo pipefail

SERVICE="amosclaud-autonomous"
ACCOUNT="${USER:?USER is required}"

printf 'Amosclaud Autonomous token: ' >&2
IFS= read -r -s TOKEN
printf '\n' >&2

if [[ -z "$TOKEN" ]]; then
  echo "Token was empty; no Keychain change was made." >&2
  exit 1
fi

security add-generic-password \
  -U \
  -a "$ACCOUNT" \
  -s "$SERVICE" \
  -w "$TOKEN" >/dev/null

unset TOKEN
echo "Stored Amosclaud token in macOS Keychain service '$SERVICE'."
