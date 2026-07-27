# Amosclaud Daily Autonomous Builder

The Daily Autonomous Builder converts an explicitly approved backlog into one or more bounded GitHub engineering tasks per UTC day. It reuses the Global Task Router, operation buckets, connected GitHub credentials, isolated verification runner, and draft pull-request delivery.

## Safety state

Autonomy is disabled unless **both** controls are enabled:

1. the server has `AMOSCLAUD_AUTONOMY_ENABLED=true`; and
2. the account has enabled autonomy through `PUT /api/v1/autonomy/settings`.

`AMOSCLAUD_AUTONOMY_PAUSED=true` is the server kill switch and overrides every account setting.

The first release has immutable rules:

- no direct push to the default branch;
- no automatic merge (`auto_merge` is constrained to false in storage and API validation);
- draft pull requests only;
- explicit repository allowlist;
- explicit writable-path allowlist;
- authentication, billing, service keys, migrations, workflows, configuration, runtime services, and deployment infrastructure protected by default;
- maximum three autonomous tasks per account per UTC day;
- maximum three configured repair attempts;
- deterministic isolated verification before publication;
- base-branch movement blocks publication;
- failed tasks refund their reserved agent tokens through the existing Global Task Router behavior.

## Runtime services

The API and Celery worker use the existing account database and task broker. Run a Celery Beat process in addition to the worker:

```bash
celery -A amoscloud_ai.worker.celery_app beat --loglevel=INFO
```

The selection pass runs at 03:00 UTC by default. Configure another hour with:

```bash
AMOSCLAUD_AUTONOMY_HOUR_UTC=3
```

The selection task is harmless while the server switch is off: it returns `server_kill_switch` and queues nothing.

## API sequence

### 1. Configure the account policy

`PUT /api/v1/autonomy/settings`

```json
{
  "enabled": true,
  "daily_limit": 1,
  "max_repair_attempts": 3,
  "allowed_repositories": ["owner/repository"],
  "allowed_paths": ["web", "tests", "docs"],
  "protected_paths": ["web/admin"],
  "staging_required": true,
  "auto_merge": false
}
```

Repositories must already be imported through the connected GitHub account.

### 2. Add a scored backlog item

`POST /api/v1/autonomy/backlog`

```json
{
  "repository": "owner/repository",
  "title": "Improve project error messages",
  "objective": "Replace ambiguous project-loading failures with actionable messages and focused regression tests.",
  "source": "user-feedback",
  "acceptance_criteria": [
    "Known project-loading failures show an actionable message",
    "Focused tests cover the new behavior",
    "Existing verification remains green"
  ],
  "user_value": 8,
  "roadmap_alignment": 7,
  "recurring_failure_reduction": 6,
  "maintainability_improvement": 4,
  "implementation_risk": 2,
  "security_risk": 1,
  "estimated_size": 3
}
```

The deterministic score is:

```text
user value
+ roadmap alignment
+ recurring failure reduction
+ maintainability improvement
- implementation risk
- security risk
- estimated size
```

Only proposed items with implementation risk at most 5, security risk at most 3, and estimated size at most 5 are eligible for automatic selection.

### 3. Run manually or wait for the daily scheduler

`POST /api/v1/autonomy/run-now`

The manual endpoint uses the same kill switches, daily limit, scoring, repository checks, token reservation, path policy, isolated verification, and draft-PR rules as the scheduled pass.

### 4. Inspect evidence

- `GET /api/v1/autonomy/runs`
- `GET /api/v1/autonomy/runs/{run_id}`
- `GET /api/v1/tasks/{task_id}`
- `GET /api/v1/tasks/{task_id}/logs`

The autonomous ledger records selection, specification, queueing, execution, verification, publication, blocking, and final state. The Global Task Router remains the source of execution evidence and verification identifiers.

## Deployment requirements

The builder requires the same infrastructure as connected GitHub tasks:

- GitHub OAuth connection with repository access;
- imported GitHub repository records;
- Celery broker and worker;
- Celery Beat for the daily selection trigger;
- configured Amosclaud model runtime;
- locked-down deterministic runner used by `RuntimeExecutor`;
- enough account agent tokens for the selected task.

Do not enable the environment switch until the worker, broker, isolated runner, GitHub integration, required checks, and emergency pause procedure have been verified in staging.
