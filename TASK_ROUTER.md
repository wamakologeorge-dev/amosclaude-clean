# Amosclaud Global Task Router

**One API for requesting verified software work from anywhere.**

The Global Task Router separates a developer's request from its execution location. Website, CLI, CI, IDE, mobile, and service clients all submit the same task contract. Amosclaud routes approved work to a runner owned by the same account.

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
  "require_approval": true
}
```

A task reserves agent credits immediately. Unstarted cancellation and failed runner completion refund that reservation.

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

## Security boundary

- No arbitrary public shell endpoint.
- No client-supplied filesystem paths are executed by the router.
- Account and runner credentials are separately scoped.
- Task ownership is checked on every read and mutation.
- Writes remain subject to the engineering agent's workspace confinement, backup, and verification controls.
- Secrets and raw runner tokens are never returned after initial creation.
