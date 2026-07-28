# Amosclaud SentinelGrid

Amosclaud SentinelGrid is an Amosclaud-native industrial autonomy control plane for supervising robots, autonomous vehicles, edge devices, charging stations, and safety sensors.

It is not affiliated with Shell or any other energy company. Approved infrastructure providers can be connected later through narrow, authenticated adapters.

## Operating sequence

SentinelGrid follows one safety-first sequence:

```text
Observe -> Diagnose -> Simulate -> Recommend -> Approve -> Dispatch -> Verify
```

The current implementation supports observation, diagnosis, simulation, recommendations, and human approval. Physical dispatch remains disabled until a separately reviewed adapter supplies device identity, command signing, allowlists, emergency-stop behavior, audit storage, and post-action verification.

## Current capabilities

- Register industrial robots, autonomous vehicles, edge nodes, chargers, and sensors.
- Persist assets, telemetry, incidents, and action proposals in the Amosclaud SQLite database.
- Ingest bounded telemetry records and accept finite numeric strings for known numeric metrics.
- Detect high methane readings, battery overheating, low charge, control-link loss, and charger faults.
- Coalesce repeated reports of the same active fault instead of creating unbounded duplicates.
- Resolve an open incident when a later reading explicitly reports that metric as healthy.
- Create software-only simulations and inspection actions.
- Create approval-gated maintenance, charging, movement, and emergency-shutdown proposals.
- Reject physical actions that are incompatible with the registered asset type or capability.
- Record the authenticated administrator or owner-key principal as the decision actor.
- Preserve the rule that approval does not equal physical execution.

## API

The API is mounted under `/api/v1/sentinel-grid`.

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/sentinel-grid` | Public capability, persistence, and safety status |
| `POST` | `/api/v1/sentinel-grid/assets` | Register an approved asset |
| `GET` | `/api/v1/sentinel-grid/assets` | List registered assets with a bounded limit |
| `POST` | `/api/v1/sentinel-grid/telemetry` | Ingest telemetry and diagnose incidents |
| `GET` | `/api/v1/sentinel-grid/incidents` | List bounded open, resolved, or all incidents |
| `POST` | `/api/v1/sentinel-grid/actions` | Propose a software or physical action |
| `GET` | `/api/v1/sentinel-grid/actions` | List action proposals with a bounded limit |
| `POST` | `/api/v1/sentinel-grid/actions/{id}/approve` | Approve a pending proposal |
| `POST` | `/api/v1/sentinel-grid/actions/{id}/reject` | Reject a pending proposal |

Every non-status route requires a signed-in administrator or `X-Amosclaud-Owner-Key`. The client cannot choose the recorded approver identity; SentinelGrid derives it from the authenticated principal.

Incident queries support `status=open`, `status=resolved`, and `limit=1..500`.

## Durable state and incident lifecycle

SentinelGrid uses the configured Amosclaud authentication database connection, so state survives application restarts and deployments that preserve the database volume. Its tables are created idempotently.

Each asset can have at most one open incident for a specific incident code. Repeated unsafe readings update that incident's `last_seen_at` and `occurrence_count`. A later healthy value resolves the incident only when the corresponding metric is present in that telemetry submission; omitted metrics do not silently clear prior faults.

Telemetry storage is bounded. Incident and action list endpoints use bounded `limit` parameters so one persistent fault cannot create an unbounded API response.

## Safety boundary

SentinelGrid does not directly drive a vehicle, move a robot, energize a charger, operate fuel equipment, or shut down industrial machinery. Controlled actions remain `execution_allowed: false` even after administrator approval.

A future physical executor must be delivered separately and must include:

- device and service identity verification;
- signed commands and replay protection;
- tenant, site, asset, and action allowlists;
- command timeouts and bounded retries;
- emergency-stop and safe-state behavior;
- tamper-resistant audit records;
- simulation and staged rollout;
- human approval for safety-critical operations;
- post-action telemetry verification.

## Product direction

SentinelGrid can later connect to charging providers, fleet systems, ROS or CARLA simulations, industrial inspection robots, predictive-maintenance services, and private edge-computing clusters through approved adapters. Provider names and endpoints must remain configuration, not hardcoded product dependencies.
