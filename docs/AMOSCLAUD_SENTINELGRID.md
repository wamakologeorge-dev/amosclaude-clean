# Amosclaud SentinelGrid

Amosclaud SentinelGrid is an Amosclaud-native industrial autonomy control plane for supervising robots, autonomous vehicles, edge devices, charging stations, and safety sensors.

It is not affiliated with Shell or any other energy company. The program is designed so approved infrastructure providers can be connected later through narrow, authenticated adapters.

## Operating sequence

SentinelGrid follows one safety-first sequence:

```text
Observe -> Diagnose -> Simulate -> Recommend -> Approve -> Dispatch -> Verify
```

The first implementation supports observation, diagnosis, simulation, recommendations, and human approval. Physical dispatch is deliberately disabled until a separately reviewed adapter supplies device identity, command signing, allowlists, emergency-stop behavior, audit storage, and post-action verification.

## Initial capabilities

- Register industrial robots, autonomous vehicles, edge nodes, chargers, and sensors.
- Ingest bounded telemetry records.
- Detect high methane readings, battery overheating, low charge, control-link loss, and charger faults.
- Produce structured incident records and recommended follow-up actions.
- Create software-only simulations and inspection actions.
- Create approval-gated maintenance, charging, movement, and emergency-shutdown proposals.
- Preserve the rule that approval does not equal physical execution.

## API

The API is mounted under `/api/v1/sentinel-grid`.

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/sentinel-grid` | Public capability and safety status |
| `POST` | `/api/v1/sentinel-grid/assets` | Register an approved asset |
| `GET` | `/api/v1/sentinel-grid/assets` | List registered assets |
| `POST` | `/api/v1/sentinel-grid/telemetry` | Ingest telemetry and diagnose incidents |
| `GET` | `/api/v1/sentinel-grid/incidents` | List diagnosed incidents |
| `POST` | `/api/v1/sentinel-grid/actions` | Propose a software or physical action |
| `GET` | `/api/v1/sentinel-grid/actions` | List action proposals |
| `POST` | `/api/v1/sentinel-grid/actions/{id}/approve` | Approve a pending proposal |
| `POST` | `/api/v1/sentinel-grid/actions/{id}/reject` | Reject a pending proposal |

Every non-status route requires a signed-in administrator or `X-Amosclaud-Owner-Key`.

## Safety boundary

SentinelGrid does not directly drive a vehicle, move a robot, energize a charger, operate fuel equipment, or shut down industrial machinery. Controlled actions remain `execution_allowed: false` even after owner approval.

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
