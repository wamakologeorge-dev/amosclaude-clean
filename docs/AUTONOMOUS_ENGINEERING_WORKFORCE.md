# Amosclaud Autonomous Engineering Workforce

Amosclaud is moving from a cloud IDE that waits for commands to an accountable software-ownership platform. A developer delegates an entire epic, product requirement, bug, refactor, review, or test objective to one Amosclaud Autonomous core. Amosclaud then owns the governed engineering lifecycle until human judgment is required.

## Product contract

A delegated write task follows this lifecycle:

```text
Understand -> Plan -> Isolated branch -> Execute -> Test -> Diagnose
           -> Bounded self-correction -> Verify -> Draft pull request
           -> Human final sign-off
```

Amosclaud must not claim success without a verification identifier and runtime evidence. It must stop safely when permissions, model runtime, execution infrastructure, repository state, tests, or policy block the work.

The user sees one work order and one evidence trail. Internal planning, coding, testing, reviewing, and monitoring stages are helpers coordinated by the same core; they are not competing visible agents.

## 1. Autonomous software ownership

### Durable delegations

The workforce control plane stores:

- the connected repository;
- work type and complete requirement;
- acceptance criteria;
- GitHub issue or product-requirement reference;
- chosen execution lane;
- immutable guardrail snapshot;
- phased plan;
- linked Global Task Router task;
- lifecycle and verification events;
- human-attention reason.

Write-capable delegations require explicit authorization. Without authorization, they enter `awaiting_approval`. Read-only test and review tasks can run without repository-write authority.

### Governed execution

The dedicated workforce runner:

1. clones the authorized connected GitHub repository;
2. records the base branch and SHA as a rollback checkpoint;
3. creates an isolated Amosclaud work branch;
4. invokes the existing engineering core;
5. enforces allowed and protected path policy;
6. runs deterministic verification in the locked-down runner;
7. feeds failure evidence back into a bounded self-correction loop;
8. confirms that the target branch did not move;
9. pushes only the isolated branch;
10. opens a draft pull request containing acceptance criteria, changed files, rollback checkpoint, and guardrail state.

The normal repair limit is one to three attempts. The runner never force-pushes, never writes directly to a protected branch, and never merges automatically.

## 2. Hybrid edge and cloud execution

The scheduler supports these execution preferences:

- `auto`: use an eligible online edge runner, otherwise use the controlled cloud/GitHub lane;
- `edge`: require an eligible private runner and fail closed when none is available;
- `cloud` or `github`: use the controlled connected-repository lane.

A private runner is eligible for engineering work only when its heartbeat explicitly advertises:

```text
engineering_workforce_v1
```

It must also advertise the requested task mode, such as `build`, `fix`, `test`, or `review`. Existing model-only stations are therefore never mistaken for code-execution workers.

The current cloud lane uses Amosclaud's durable Celery task queue, connected GitHub authorization, isolated verification runner, and draft-pull-request delivery. Long-term execution hosts can be Docker, Kata Containers, or Firecracker microVMs without changing the delegation API.

## 3. Universal Software Asset Dashboard

A software asset can represent a service, micro-SaaS product, data pipeline, algorithmic agent, library, or website. Each asset can be linked to a repository and environment.

The dashboard aggregates reported telemetry for:

- online/offline/degraded/stale state;
- 24-hour uptime;
- average latency;
- CPU and memory;
- errors and request volume;
- active users;
- revenue telemetry in USD;
- completed and failed autonomous patches;
- patch success rate;
- recent operational events.

Each asset receives a one-time telemetry credential. Amosclaud stores only its SHA-256 hash. Telemetry and event metadata are recursively bounded and redacted before persistence. Credentials are not included in portable asset manifests.

The transfer manifest contains asset identity, repository reference, environment, licensing reference, transfer notes, and a health snapshot. A recipient must independently authorize credentials and environment secrets.

## 4. Enterprise guardrails

These controls are immutable in the workforce policy:

- isolated execution required;
- deterministic tests or verification required;
- draft pull request required;
- human merge required;
- rollback checkpoint required;
- secret masking required;
- force push disabled;
- direct protected-branch writes disabled;
- automatic merge disabled;
- production deployment approval required.

An account can narrow the permitted repository paths, expand protected paths, set protected branch names, choose a work-branch prefix, and select a bounded repair limit. It cannot turn off the immutable controls through the API.

## API surface

The routes are mounted under `/api/v1/workforce`:

```text
GET  /overview
GET  /repositories
GET  /execution-fabric
GET  /guardrails
PUT  /guardrails
POST /delegations
GET  /delegations
GET  /delegations/{id}
POST /delegations/{id}/approve
POST /delegations/{id}/cancel
POST /assets
GET  /assets
GET  /assets/{id}
POST /assets/{id}/telemetry
POST /assets/{id}/events
POST /assets/{id}/rotate-token
GET  /assets/{id}/manifest
```

The interactive dashboard is available at `/static/workforce.html` and is linked from the Command Center.

## Deployment requirements

The workforce reuses existing Amosclaud infrastructure:

- authenticated accounts and connected GitHub repositories;
- encrypted GitHub OAuth credential storage;
- persistent SQLite database today, with PostgreSQL as the scale-out target;
- Redis/Celery broker, worker, and recovery flow for production background work;
- configured model runtime for code-generating tasks;
- locked-down deterministic runner used by `RuntimeExecutor`;
- GitHub branch protection and required checks;
- optional online edge runners that implement the workforce execution contract.

A production deployment must not expose platform credentials inside project processes or private runners.

## Implemented foundation versus later platform phases

Implemented in this phase:

- complete work-order delegation;
- explicit write authorization;
- durable task and event linkage;
- isolated GitHub work branches;
- bounded self-correction;
- verification-gated draft pull requests;
- rollback checkpoints;
- edge-first scheduler contract with cloud fallback;
- software-asset registration and authenticated telemetry ingestion;
- operational, functional, usage, revenue, and patch-success aggregation;
- portable secret-free asset manifests;
- immutable safety guardrails;
- responsive workforce dashboard.

Not represented as complete yet:

- a native Amosclaud-repository branch and pull-request delivery adapter;
- a downloadable desktop edge launcher;
- automatic probing of arbitrary external asset URLs;
- Railway, Render, AWS, and GCP release adapters from the Asset Dashboard;
- multi-region scheduling and elastic cluster autoscaling;
- licensing payments, asset marketplace, escrow, or investment transfer workflows;
- MCP connector registry and organization-wide policy packs.

Those capabilities can be added behind the same delegation, execution-fabric, asset, and guardrail contracts without weakening the current safety boundaries.
