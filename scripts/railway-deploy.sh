#!/usr/bin/env sh
set -eu

EXPECTED_SERVICE="${RAILWAY_EXPECTED_SERVICE:-amosclaude-clean}"

if ! command -v railway >/dev/null 2>&1; then
  echo "Railway CLI is required: https://docs.railway.com/guides/cli"
  exit 1
fi

STATUS_OUTPUT="$(railway status 2>&1 || true)"

if [ -z "$STATUS_OUTPUT" ]; then
  echo "This repository is not linked to a Railway project."
  echo "Run: railway link"
  exit 1
fi

if ! printf '%s\n' "$STATUS_OUTPUT" | grep -qi "$EXPECTED_SERVICE"; then
  echo "Refusing to deploy: linked Railway service does not match '$EXPECTED_SERVICE'."
  echo "Current Railway status:"
  printf '%s\n' "$STATUS_OUTPUT"
  echo "Set RAILWAY_EXPECTED_SERVICE only when intentionally deploying another service."
  exit 1
fi

echo "Deploying to the existing Railway service: $EXPECTED_SERVICE"
railway up --service "$EXPECTED_SERVICE"
