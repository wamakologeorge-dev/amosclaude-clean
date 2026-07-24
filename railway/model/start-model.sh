#!/bin/sh
set -eu

MODEL="${AMOSCLAUD_MODEL:-qwen2.5-coder:3b}"

ollama serve &
SERVER_PID=$!

cleanup() {
  kill "$SERVER_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

attempt=0
until ollama list >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 60 ]; then
    echo "Amosclaud model service did not become ready" >&2
    exit 1
  fi
  sleep 2
done

if ! ollama list | awk 'NR > 1 {print $1}' | grep -Fxq "$MODEL"; then
  echo "Downloading Amosclaud model: $MODEL"
  ollama pull "$MODEL"
fi

echo "Amosclaud model service is ready with $MODEL"
wait "$SERVER_PID"
