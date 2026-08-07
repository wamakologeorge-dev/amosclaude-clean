# Amosclaud Developer Control Plane

## Purpose

Amosclaud gives a developer one account, dashboard, permission system, and audit trail while allowing work to execute on infrastructure the developer chooses.

```text
Developer
    │
    ▼
amosclaud.com
Account, dashboard and permissions
    │
    ▼
Amosclaud Control Plane
Creates and signs authorized jobs
    │
    ├──────────────────┬──────────────────┐
    ▼                  ▼                  ▼
Local computer    Private server    GitHub repository
Amosclaud Runner  Amosclaud Runner  GitHub App
```

The Control Plane is an authorization service. It does not need to perform a repository build itself. It decides what may happen, creates a bounded job, signs the authorization, and sends it to an execution adapter.

## Developer trust contract

Every executable job must answer these questions before a runner touches developer resources:

1. Which Amosclaud account approved the job?
2. Which workspace owns it?
3. Which execution target may run it?
4. Is it bound to a specific runner?
5. What repository and objective are in scope?
6. Which permissions were approved?
7. Has the authorization expired?
8. Has any field changed after Amosclaud signed it?
9. Can a retry be handled without performing the operation twice?

The `amosclaud.control-plane.job.v1` envelope answers those questions with a short-lived Ed25519 signature.

## Job lifecycle

```text
Developer submits a task
        │
        ▼
Account and workspace permissions are checked
        │
        ▼
Sensitive capabilities require explicit approval
        │
        ▼
Control Plane creates a five-minute authorization
        │
        ▼
Canonical authorization payload is signed with Ed25519
        │
        ├──────── Local/private runner pulls the job
        │
        └──────── GitHub App receives the job
                         │
                         ▼
Execution adapter verifies signature, expiry and bindings
                         │
              ┌──────────┴──────────┐
              │                     │
              ▼                     ▼
          Verified              Rejected
              │                     │
              ▼                     ▼
     Run only allowed work    Record security event
              │
              ▼
     Return evidence and artifacts
              │
              ▼
       Control Plane audit log
```

## Execution targets

### Local computer

A developer installs `amosclaud-runner` on a laptop or workstation. The runner is paired to one Amosclaud account and workspace. Jobs can inspect code, create isolated workspaces, run tests, and prepare patches without uploading the complete repository to Amosclaud.

The runner must verify:

- the pinned Amosclaud Control Plane public key;
- the expected account and workspace;
- `target=local_computer`;
- its own `runner_id`, when the job is runner-bound;
- job expiry and request digest;
- every requested permission.

### Private server

The same runner software can be installed on a developer-owned server. Private servers may offer additional capabilities such as container builds, artifact storage, monitoring, or approved deployments.

A deployment authorization is sensitive. It must contain `deployment:execute` and `sensitive_approved=true`; otherwise the signing library refuses to create the job.

### GitHub repository

The GitHub App is an execution adapter, not the owner of the task. It verifies `target=github_repository` and then uses the repository installation permissions already approved by the developer.

The GitHub App should normally receive narrow capabilities such as:

- `repository:read`;
- `github:issue:create`;
- `github:pull_request:create`;
- `patch:create`.

Repository deletion, secret access, credential changes, and production deployment remain sensitive operations.

## Signed envelope

The public contract is defined in:

```text
schemas/amosclaud-control-plane-job-v1.schema.json
```

Representative envelope:

```json
{
  "protocol": "amosclaud.control-plane.job.v1",
  "algorithm": "Ed25519",
  "key_id": "cp_9f31d12b77d14e22",
  "authorization": {
    "job_id": "task_123",
    "account_id": "42",
    "workspace_id": "workspace_primary",
    "target": "local_computer",
    "objective": "Run tests and prepare a verified patch.",
    "permissions": [
      "patch:create",
      "repository:read",
      "tests:run",
      "workspace:write"
    ],
    "repository": "owner/repository",
    "runner_id": "runner_laptop",
    "issued_at": "2026-08-06T18:00:00Z",
    "expires_at": "2026-08-06T18:05:00Z",
    "nonce": "one-time-random-value",
    "idempotency_key": "64-character-sha256-value",
    "request_sha256": "64-character-sha256-value",
    "request": {
      "branch": "main",
      "mode": "fix"
    },
    "sensitive_approved": false
  },
  "signature": "base64url-ed25519-signature"
}
```

## Permission model

Safe capabilities can be included after normal account and workspace authorization:

- repository and workspace reads;
- isolated workspace writes;
- tests;
- patch creation;
- logs and artifacts;
- issue and pull-request creation;
- deployment preparation;
- monitoring reads.

Sensitive capabilities require a separate approval decision:

- secret access;
- credential rotation;
- account administration;
- billing changes;
- production deployment execution;
- repository deletion.

The distinction is enforced by the signing library, not only by the dashboard interface.

## Key management

The private Ed25519 signing material belongs only to the Amosclaud Control Plane. It must never be sent to a browser, runner, GitHub workflow, repository, log, or job envelope.

Execution adapters receive a public identity containing:

```json
{
  "protocol": "amosclaud.control-plane.job.v1",
  "algorithm": "Ed25519",
  "key_id": "cp_...",
  "public_key": "base64url-public-key"
}
```

Production deployments must use a stable secret or dedicated key store. Rotations should publish a new `key_id`, allow a brief overlap for in-flight jobs, and then revoke the previous identity.

## Existing Amosclaud foundation

The repository already contains account authentication, workspaces, operation buckets, task approvals, runner registration, runner heartbeats, self-hosted job claiming, GitHub App integration, and verified task completion evidence.

The first Control Plane implementation adds the missing portable trust boundary. The next integration slice should:

1. classify registered runners as `local_computer` or `private_server`;
2. wrap every claimed task in a signed authorization envelope;
3. publish the current public Control Plane identity;
4. require runner verification before execution;
5. route GitHub jobs through the same envelope;
6. record signature key, target, permissions, nonce, and idempotency key in the audit trail;
7. add dashboard permission previews before approval.

## Security invariant

> No Amosclaud runner or GitHub adapter should perform work merely because it received a task ID. It should perform work only after verifying a current, correctly scoped, developer-authorized Control Plane signature.
