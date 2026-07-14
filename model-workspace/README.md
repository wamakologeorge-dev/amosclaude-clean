# Amosclaud Folder Model

This workspace creates and runs an Amosclaud-owned bootstrap language model without an
OpenAI, Anthropic, or hosted-model API key. Its corpus, tokenizer vocabulary, checkpoint,
logs, and configuration remain in one movable folder.

```text
model-workspace/
├── config/model.json
├── datasets/
│   ├── raw/                 # Imported code and text
│   ├── curated/             # Reviewed instruction examples
│   └── manifest.jsonl       # Dataset provenance
├── tokenizer/vocab.json     # Created during training
├── checkpoints/current.json # Atomically replaced checkpoint
└── logs/service/           # Tamper-evident inference events
```

Create a writable runtime workspace and train it:

```bash
export AMOSCLAUD_MODEL_HOME="$HOME/.amosclaud/model"
amosclaud-model init
amosclaud-model import ./my-licensed-training-folder --license apache-2.0
amosclaud-model import ./model-workspace/datasets/curated --license project-owned
amosclaud-model train
amosclaud-model evaluate
amosclaud-model checkpoints
amosclaud-model chat "How should I verify this patch?"
amosclaud-model serve --host 127.0.0.1 --port 8091
```

Connect the main server:

```env
AMOSCLAUD_MODEL_URL=http://127.0.0.1:8091
AMOSCLAUD_MODEL=amosclaud-folder-v1
```

The local service is keyless by default. Set `AMOSCLAUD_MODEL_TOKEN` when exposing it across
a network. The HTTP interface provides `/health`, `/v1/models`, and
`/v1/chat/completions`.

This first checkpoint is deliberately compact and proves fully owned training and inference.
It is not equivalent to a frontier coding model. Capability grows with reviewed, licensed
datasets and later neural checkpoints; do not train on repositories or personal data without
permission.

## Model service log

Every inference appends a JSONL event under `logs/service/`. Records contain request and
checkpoint identity, token counts, latency, outcome, and a one-way prompt fingerprint.
Raw prompts, responses, credentials, and API tokens are never stored. Events form a
SHA-256 chain so edits or missing records inside the retention window are detectable.

```bash
amosclaud-model logs --limit 25
amosclaud-model log-summary
amosclaud-model verify-logs
```

Authenticated servers expose `/v1/logs`, `/v1/logs/summary`, and `/v1/logs/verify`.
Retention defaults to 30 days; configure `AMOSCLAUD_MODEL_LOG_RETENTION_DAYS`. Set
`AMOSCLAUD_MODEL_LOG_HASH_KEY` to use keyed HMAC fingerprints.

Training writes immutable versions under `checkpoints/versions`, records SHA-256 integrity and
evaluation metrics in `checkpoints/index.jsonl`, and atomically promotes the new checkpoint.
Use `amosclaud-model promote CHECKPOINT_ID` or `amosclaud-model rollback` to recover a known
checkpoint. Evaluation examples belong in `datasets/eval` and are never included in training.
