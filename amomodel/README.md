# AmoModel

AmoModel is the governed control plane for the Amosclaud software-engineering platform. It is deterministic, inspectable, database-backed, and does not claim to be a neural model. It never executes arbitrary shell commands and never marks repair work complete without CI verification evidence.

## Responsibilities

AmoModel provides:

- runtime power, restart, readiness, and degraded-state control;
- dependency-aware health evidence for the database, Byte bus, repository, Agent, fixer, CI, pull-request, and deployment services;
- persistent JSON lifecycle and audit state;
- shared-database creation of `AutonomousJob` and `CIPipeline` records;
- truthful planning-only execution when no repository is selected;
- queued Autonomous or fixer work when a repository is selected;
- job and verification status lookup.

The shared SQLAlchemy database remains authoritative for users, repositories, pull requests, CI pipelines, Autonomous jobs, and verification IDs. The JSON state file stores only local runtime lifecycle and audit evidence.

## States

`off`, `starting`, `ready`, `busy`, `degraded`, `stopping`, `failed`

## API

- `GET /api/v1/amomodel/status`
- `POST /api/v1/amomodel/power/on`
- `POST /api/v1/amomodel/power/off`
- `POST /api/v1/amomodel/restart`
- `POST /api/v1/amomodel/execute`
- `GET /api/v1/amomodel/jobs/{task_id}`

Status and job lookup require an authenticated session. Lifecycle and execution operations require an administrator.

## Execute modes

`plan`, `build`, `test`, `review`, `deploy`, `monitor`, `fix`

A request without `repository_id` performs governed planning and readiness inspection only. A request with `repository_id` creates a queued platform job and pending CI pipeline. `fix` mode selects the `amosclaud-fixer` worker; the other repository modes select `amosclaud-autonomous`.

Example request:

```json
{
  "objective": "Repair the failing repository tests",
  "mode": "fix",
  "repository_id": 12,
  "pull_request_id": 4,
  "target_file": "tests/test_routes.py",
  "error_context": "pytest collection failed",
  "commit_sha": "abc123"
}
```

The response includes a `task_id` and `ci_pipeline_id`. The task remains queued until an approved worker claims it, and it cannot become passed without a verification ID.

## Local state

Lifecycle state is persisted at `data/amomodel/state.json` by default. Set `AMOMODEL_STATE_PATH` to override it. Platform job data uses `AMOSCLAUD_PLATFORM_DATABASE_URL` through the shared `database/` package.
