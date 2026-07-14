# Amosclaud Global Task Router

**One API for requesting verified software work from anywhere.**

The Global Task Router separates a developer's request from its execution location. Website, CLI, CI, IDE, mobile, and service clients all submit the same task contract. Amosclaud routes approved work to its cloud runtime, a private self-hosted runner, or a connected GitHub repository.

## Submit a task

```http
POST /api/v1/tasks
Authorization: Bearer amos_live_customer_key
Content-Type: application/json

{
  "repository": "owner/project",
  "objective": "Fix the failing Python tests and prepare a pull request",
  "mode": "build",
  "delivery": "pull_request",
  "execution_target": "github",
  "require_approval": true
}
```

`execution_target` accepts `auto`, `cloud`, `self_hosted`, or `github`. Automatic routing selects a named private runner first, then a connected repository, then the cloud runtime. Self-hosted tasks must include `runner_id`; GitHub tasks must include `repository`.

A task reserves agent credits immediately. Unstarted cancellation and failed runner completion refund that reservation.

## Execution targets

| Target | Intended work | Result |
|---|---|---|
| `cloud` | Questions and managed execution | Report, evidence, or artifact |
| `self_hosted` | Work inside a developer-controlled folder | Patch, tests, logs, or report |
| `github` | Work on an imported, connected repository | Verified patch and optional pull request |

All targets use the same task ID, lifecycle, ownership checks, event log, approval gate, and credit reservation.

## Lifecycle

```text
awaiting_approval -> queued -> running -> completed
                                  \-> failed
awaiting_approval/queued -> cancelled
```

## Developer API

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/v1/tasks` | Submit verified work |
| GET | `/api/v1/tasks` | List owned tasks |
| GET | `/api/v1/tasks/{id}` | Read task status |
| GET | `/api/v1/tasks/{id}/logs` | Read evidence events |
| POST | `/api/v1/tasks/{id}/approve` | Approve routing |
| POST | `/api/v1/tasks/{id}/cancel` | Cancel unstarted work |
| POST | `/api/v1/runners` | Register a private runner |
| GET | `/api/v1/runners` | List private runners |

## Runner protocol

A runner credential is displayed once and stored only as a hash. Runners communicate outbound to Amosclaud:

1. `POST /api/v1/runners/{id}/heartbeat`
2. `POST /api/v1/runners/{id}/claim`
3. Perform work inside the configured local workspace.
4. `POST /api/v1/runners/{id}/tasks/{task_id}/complete`

Runner credentials cannot access account or billing endpoints. A runner can claim only its owner's queued tasks. Claiming is transactional to prevent duplicate execution.

Start the downloadable runner from its configured folder with:

```bash
export AMOSCLAUD_API_URL="https://amosclaud.com"
export AMOSCLAUD_RUNNER_ID="runner_..."
export AMOSCLAUD_RUNNER_TOKEN="amos_runner_..."
export AMOSCLAUD_RUNNER_WORKSPACE="/absolute/path/to/project"
amosclaud-runner
```

The packaged installer can configure this pairing interactively. After pairing, the runner makes outbound authenticated heartbeat and claim requests; the router never scans the local network and does not expose an inbound control port.

## Security boundary

- No arbitrary public shell endpoint.
- No client-supplied filesystem paths are executed by the router.
- Account and runner credentials are separately scoped.
- Task ownership is checked on every read and mutation.
- Writes remain subject to the engineering agent's workspace confinement, backup, and verification controls.
- Secrets and raw runner tokens are never returned after initial creation.
