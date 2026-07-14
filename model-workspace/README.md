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
amosclaud-model license-audit
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

## Protected training service

The model server can train or evaluate in the background without blocking inference-control
requests. Only one job runs at a time, and job state survives in `training/jobs/`.

```bash
curl -X POST http://127.0.0.1:8091/v1/training/jobs \
  -H "Authorization: Bearer $AMOSCLAUD_MODEL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"operation":"train"}'
curl http://127.0.0.1:8091/v1/training/jobs \
  -H "Authorization: Bearer $AMOSCLAUD_MODEL_TOKEN"
```

The service refuses training until every imported dataset record has an approved rights label.
Built-in labels are `project-owned`, `Amosclaud project-owned`, `MIT`, `Apache-2.0`,
`BSD-2-Clause`, `BSD-3-Clause`, `CC0-1.0`, and `commercial-license`. A legal review can add
organization-specific labels with `AMOSCLAUD_TRAINING_LICENSE_ALLOWLIST`. This allowlist is a
technical control, not a substitute for actual permission.

There is no universal training license. For every dataset, keep its license or signed contract,
source URL, acquisition date, allowed purposes, attribution requirements, privacy review, and
deletion obligations. Use `project-owned` only when Amosclaud owns the material or contributors
have explicitly granted training rights. A public repository with no license remains
`unverified` and must not be imported.
