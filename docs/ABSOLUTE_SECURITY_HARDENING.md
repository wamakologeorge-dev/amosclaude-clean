# Amosclaud Absolute Security Hardening Program

This program is the production-readiness gate for Amosclaud as a multi-user SaaS.
Public deployment is not considered approved until every security gate below is
implemented and verified.

## Deployment model

- Product: multi-user Amosclaud SaaS
- Primary API: FastAPI/Uvicorn (`amoscloud_ai.main:app`)
- Legacy workflow dashboard requiring hardening: root `app.py`
- Background execution: Celery/Redis or Amosclaud Task Router
- Untrusted code: isolated runner containers or isolated server stations only
- Preview hosting: dedicated preview service, never the main API process

## Gate 1 — Authentication and tenant isolation

- Require an authenticated Amosclaud session or approved service credential for
  every non-public API operation.
- Keep only health, login/registration, OAuth callbacks, and explicitly signed
  webhook endpoints public.
- Add `owner_user_id` to projects, variables, runs, and artifacts.
- Filter every read, write, update, and delete by both resource identifier and
  `owner_user_id`.
- Return 404 for resources owned by another tenant to avoid resource discovery.
- Add migration coverage and cross-tenant access tests.

## Gate 2 — Safe code execution

- Remove `shell=True` from production execution paths.
- Never execute build or test commands inside the API process.
- Enqueue work through Celery/Redis or Amosclaud Task Router.
- Execute untrusted work only inside an isolated runner container or isolated
  server station.
- Enforce an executable allowlist, argument validation, strict timeouts, CPU and
  memory limits, PID limits, a read-only root filesystem, temporary filesystems,
  and no network by default.
- Do not mount the Docker socket or host credentials into a user workload.

## Gate 3 — Secret handling

- Encrypt stored secret values at rest with a deployment-managed key.
- Never return encrypted values, decrypted values, verification tokens, API keys,
  or secret environment variables to browsers.
- Redact known secret values from worker logs before persistence and display.
- Pass secrets to workers through protected runtime channels, not command-line
  arguments or repository files.

## Gate 4 — Asynchronous production architecture

- API requests create queued run records and return immediately.
- Workers own state transitions: queued, running, succeeded, failed, cancelled.
- Persist job state in the platform database; never rely on process-local state.
- Provide polling endpoints scoped to the authenticated owner.
- Retry only idempotent operations and record all attempts.

## Gate 5 — Isolated preview service

- Publish generated sites to a separate preview service.
- Use opaque preview identifiers and owner-scoped publish credentials.
- Serve previews behind a reverse proxy with strict headers and content isolation.
- Require DNS TXT ownership verification before attaching a custom domain.
- Never run generated applications inside the main API process.

## Gate 6 — Repository and configuration cleanup

- Move toward explicit application boundaries for dashboard/frontend, API,
  workers/runners, CLI/SDK, mobile, and model services.
- Define canonical package names and compatibility shims before deleting legacy
  import paths.
- Consolidate environment examples into a central configuration catalog with
  service-specific overlays.
- Complete cleanup through small migration pull requests with compatibility and
  import-contract tests.

## Approval policy

Low-risk, deterministic background repairs may auto-merge only after all required
checks pass. Security, authentication, infrastructure, workflow, permission,
secret-management, and production-deployment changes remain high risk and use the
single-use GitHub approval command:

```text
@amosclaud approve
```

Approval must be made by an OWNER, MEMBER, or COLLABORATOR, is bound to one exact
objective, and is consumed after one execution. Denial uses:

```text
@amosclaud deny
```

## Release gate

A production release is blocked when any of these are true:

- an API data route is unauthenticated;
- tenant-owned data is not filtered by `owner_user_id`;
- a production execution path uses `shell=True`;
- untrusted commands can run in the API container;
- secret values can be returned to the browser or persisted unredacted in logs;
- generated previews are hosted in the main API process;
- custom domains can be attached without DNS TXT verification.
