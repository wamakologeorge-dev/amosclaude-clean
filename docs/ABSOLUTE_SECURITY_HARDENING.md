# Amosclaud Absolute Security Hardening Program

This program is the production-readiness gate for Amosclaud as a multi-user SaaS.
Public deployment is not approved until every security gate below is implemented
and verified.

## Deployment model

- Product: multi-user Amosclaud SaaS
- Primary API: FastAPI/Uvicorn (`amoscloud_ai.main:app`)
- Legacy workflow dashboard hardened in root `app.py`
- Background execution: Celery/Redis or Amosclaud Task Router
- Untrusted code: isolated runner containers or isolated server stations only
- Preview hosting: dedicated preview service, never the main API process

## Gate 1 — Authentication and tenant isolation

Every non-public data operation requires an authenticated Amosclaud session or an
explicit service credential. Projects, variables, runs, and artifacts carry an
`owner_user_id`, and every query includes both the resource identifier and owner.
Cross-tenant requests return `404` instead of revealing that another tenant owns
the resource.

Existing dashboard rows are assigned to no user (`owner_user_id=0`) and are
therefore inaccessible. An operator may perform an explicit one-time migration by
setting `AMOSCLAUD_LEGACY_OWNER_USER_ID` to the destination user ID before startup.

## Gate 2 — Safe code execution

The API enqueues run records and returns immediately. A Celery worker executes the
job with `amoscloud_ai.isolated_runner` inside a pre-provisioned Docker image.
The runner uses argument vectors rather than a shell and enforces:

- executable allowlisting;
- no container network;
- CPU, memory, and PID limits;
- a read-only root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges`;
- a bounded temporary filesystem;
- a non-root user;
- strict execution timeouts;
- no Docker socket or host credential mount.

Required production variables include:

```text
AMOSCLAUD_RUNNER_IMAGE=<prebuilt-image>
AMOSCLAUD_RUNNER_ALLOWLIST=python,python3,pip,pip3,pytest,node,npm,npx,pnpm,yarn,make
AMOSCLAUD_RUNNER_CPUS=1.0
AMOSCLAUD_RUNNER_MEMORY=768m
AMOSCLAUD_RUNNER_PIDS_LIMIT=128
AMOSCLAUD_RUNNER_TIMEOUT_SECONDS=600
CELERY_BROKER_URL=<redis-or-broker-url>
CELERY_RESULT_BACKEND=<redis-or-backend-url>
```

## Gate 3 — Secret handling

Project variables are encrypted at rest. Values are never returned to browsers,
including variables marked non-secret. DNS verification tokens are returned only
when newly generated and are omitted from normal project responses. Worker output
is redacted against every injected secret before logs are persisted.

Production requires a deployment-managed Fernet key:

```text
AMOSCLAUD_DASHBOARD_KEY=<fernet-key>
```

## Gate 4 — Asynchronous job state

API requests create `queued` runs. Workers own subsequent transitions to
`running`, `succeeded`, or `failed`. State is persisted in SQLite for the legacy
dashboard and must use the platform database before horizontal scaling.

## Gate 5 — Isolated previews

Generated applications are not started inside the API or deployment worker.
Verified output must be published to a separate preview service. That service must
use opaque preview IDs, owner-scoped publish credentials, a reverse proxy with
strict response headers, and DNS TXT verification before a custom domain is
attached.

## Gate 6 — Repository and configuration cleanup

The repository will be migrated through small compatibility-preserving changes
into explicit application boundaries for frontend/dashboard, API, workers,
runners, CLI/SDK, mobile, and model services. Environment examples will move to a
central catalog with service-specific overlays. Legacy import paths remain only as
tested shims during migration.

## Approval policy

Low-risk deterministic background repairs may auto-merge only after all required
checks pass. Authentication, security, infrastructure, workflow, permission,
secret-management, and production deployment changes are high risk and use the
single-use GitHub approval command:

```text
@amosclaud approve
```

Only an OWNER, MEMBER, or COLLABORATOR may approve. Approval is bound to one exact
normalized objective and consumed after one execution. Denial uses:

```text
@amosclaud deny
```

## Remaining production blockers

This foundation does not by itself authorize public release. Release remains
blocked until the following follow-up work is complete:

1. Move dashboard state from standalone SQLite to the shared platform database.
2. Implement the dedicated preview publishing service and reverse proxy.
3. Audit and remove every remaining production-reachable `shell=True` path.
4. Consolidate package and environment layouts without breaking compatibility.
5. Complete cross-tenant integration tests against the deployed API gateway.
