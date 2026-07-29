#!/usr/bin/env bash
set -euo pipefail

MODEL_NAME="${OLLAMA_MODEL_NAME:-wamakologeorge/amosclaud-clean:latest}"
BASE_MODEL="${OLLAMA_BASE_MODEL:-llama3.2}"
MODELFILE="${OLLAMA_MODELFILE:-models/ollama/Modelfile}"
PROBE_TOKEN="AMOSCLAUD_MODEL_READY"

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama CLI is required. Install it from https://ollama.com/download." >&2
  exit 1
fi

if [[ ! -f "$MODELFILE" ]]; then
  echo "Modelfile not found: $MODELFILE" >&2
  exit 1
fi

case "$MODEL_NAME" in
  */*:*) ;;
  *)
    echo "Model name must use namespace/name:tag, for example wamakologeorge/amosclaud-clean:latest." >&2
    exit 1
    ;;
esac

echo "Pulling base model: $BASE_MODEL"
ollama pull "$BASE_MODEL"

echo "Creating model: $MODEL_NAME"
ollama create "$MODEL_NAME" -f "$MODELFILE"

echo "Running local readiness probe"
probe_output="$(ollama run "$MODEL_NAME" "Reply with exactly: $PROBE_TOKEN")"
if [[ "$probe_output" != *"$PROBE_TOKEN"* ]]; then
  echo "Local model probe failed; the model was not pushed." >&2
  exit 1
fi

echo "Pushing model to Ollama"
echo "This step requires an Ollama account and a registered Ollama public key."
ollama push "$MODEL_NAME"

echo "Published $MODEL_NAME successfully."
echo "Next, set the GitHub Actions repository variable AMOSCLAUD_MODEL=$MODEL_NAME"
echo "and run the Ollama Model Verify workflow before making it the production route."
