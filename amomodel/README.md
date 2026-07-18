# AmoModel

AmoModel is a folder-native, governed software runtime for Amosclaud. It uses deterministic code, persisted JSON state, an inspectable service graph, and authenticated lifecycle APIs. It does not claim to be a neural model and never executes arbitrary shell commands.

## States

`off`, `starting`, `ready`, `busy`, `degraded`, `stopping`, `failed`

## API

- `GET /api/v1/amomodel/status`
- `POST /api/v1/amomodel/power/on`
- `POST /api/v1/amomodel/power/off`
- `POST /api/v1/amomodel/restart`
- `POST /api/v1/amomodel/execute`

Status requires an authenticated session. Lifecycle and execution operations require an administrator. State is persisted at `data/amomodel/state.json` by default; set `AMOMODEL_STATE_PATH` to override it.

The first execution engine is intentionally bounded: it accepts and records an objective, reports the governed service evidence, and does not fabricate generated files, model output, or external work.
