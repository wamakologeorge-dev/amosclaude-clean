# Amosclaud Developer Cloud Architecture

This document defines the target architecture for Amosclaud as a complete developer platform rather than a web terminal wrapper.

## Design principles

1. **Real execution, never simulated success.** Terminal output, commits, agent changes, tests, builds, and deployments must come from an actual runtime and return evidence.
2. **Folder-first persistent state.** A repository is the durable unit of work. Stopping a runtime must not remove files, history, issues, or authorized configuration.
3. **Credentials stay outside project processes.** GitHub, deployment, model, and platform credentials remain in the control plane or a dedicated secret authority.
4. **Isolate untrusted project execution.** The production multi-user execution plane uses a separate Docker, Kata Containers, or Firecracker host. The same-service managed runtime is an owner-operated bridge for deployments that do not yet have that execution plane.
5. **One connected workflow.** Edit, run, debug, diagnose, repair, verify, commit, synchronize, deploy, and monitor from the same repository workspace.

## 1. Core workspace and execution engine

### Production execution plane

Each active workspace is provisioned into an isolated container or microVM with:

- a non-root developer identity;
- CPU, memory, PID, capability, filesystem, and network limits;
- a persistent repository mount;
- ephemeral process state;
- Bash, POSIX shell, and Python profiles;
- language and build tools supplied by a versioned workspace image;
- short-lived, single-use terminal tickets;
- a PTY transported over WebSocket;
- tmux-backed reconnectable sessions;
- explicit port discovery and forwarding policy.

The repository already includes a Docker workspace runtime and xterm.js PTY transport. It remains the preferred boundary for a public multi-user Amosclaud service.

### Managed deployment bridge

When the isolated runtime is not configured or is unavailable, Amosclaud can use the same public service as a managed terminal bridge. This bridge:

- is owner-only;
- uses signed, single-use terminal tickets;
- launches a repository-scoped PTY;
- uses a scrubbed environment with no platform credentials;
- uses a stable non-root UID when the host permits identity changes;
- streams real command and debugger output;
- preserves repository files and Git history.

It is not a replacement for container or microVM isolation at large multi-user scale.

### Live run and debug contract

Every command started from Project tools emits lifecycle evidence:

1. `running` with command, terminal, provider, and start time;
2. continuously streamed stdout/stderr and interactive input;
3. `success`, `failed`, or `interrupted` with exit status and duration;
4. a user-controlled interrupt action equivalent to `Ctrl+C`.

Debugger support includes Python `pdb`, Node inspector mode, GDB, strace, and project-defined debug commands.

## 2. Backend control plane and API

The control plane uses FastAPI, Uvicorn, and Pydantic to coordinate:

- authentication and repository authorization;
- workspace provisioning and status;
- terminal ticket issuance;
- agent operations;
- GitHub pull, push, and Sync & Push;
- CI/CD triggers and deployment hooks;
- health, activity, and audit evidence.

### Database progression

The current deployment uses persistent SQLite storage. Schema repair must be idempotent so older Railway volumes upgrade without losing data.

The scale-out target is PostgreSQL with SQLAlchemy and Alembic for:

- users, organizations, and role bindings;
- repository and workspace mappings;
- operation buckets and agent runs;
- environment-variable references;
- deployment records;
- audit and verification evidence.

### Secrets authority

Project processes must never receive broad platform credentials. A dedicated authority should:

- encrypt secrets at rest;
- scope access by user, organization, repository, environment, and operation;
- issue short-lived credentials where supported;
- redact likely credentials from terminal and agent context;
- record access in an audit trail;
- prevent secret values from entering commits, logs, or public repositories.

## 3. Autonomous AI engineering agents

The agent layer follows a governed engineering loop:

`Plan -> Execute -> Observe -> Test -> Diagnose -> Fix -> Verify -> Report`

The terminal agent hub exposes:

- **Doctor:** read-only diagnosis;
- **Fixer:** bounded authorized repair;
- **Autonomous:** end-to-end engineering task;
- **Underground Fixer:** bounded escalation after normal repair fails.

No agent may claim success without runtime evidence. Repository writes require explicit authorization. Underground mode cannot force-push, bypass checks, or write protected branches.

### Model and MCP targets

The platform supports model-backed execution through configured model endpoints. The next protocol layer should add MCP clients and servers for:

- GitHub repository, issue, pull-request, and workflow context;
- terminal and test output;
- repository graphs and semantic code search;
- deployment providers;
- documentation and organization knowledge.

MCP credentials remain server-side and are scoped through the secrets authority.

## 4. CI/CD and global deployment

### Continuous verification

Commits and pull requests trigger automated checks for:

- unit and integration tests;
- formatting and linting;
- type and package validation;
- container builds;
- security analysis;
- real-operation audits.

The terminal Problems cell and Doctor agent provide the same verification evidence interactively before a push.

### Deployment connector target

A deployment connector interface should normalize Railway, Render, AWS, and GCP operations:

- validate configuration;
- select repository, branch, and commit;
- resolve scoped environment secrets;
- build and release;
- stream deployment logs;
- record the resulting URL and revision;
- execute health checks;
- support rollback without rewriting source history.

## 5. Distribution and developer experience

### Web workspace

The web workspace provides:

- xterm.js terminal tabs and split sessions;
- responsive mobile and desktop layout;
- repository file editing;
- smart run, test, build, lint, and debug commands;
- live process state and stop control;
- Ports, Problems, Connectors, and Network cells;
- agent context sharing with credential redaction;
- GitHub Pull, Push, and safe Sync & Push.

### Local-first bridge target

A future signed desktop launcher or native CLI should connect local folders to Amosclaud without replacing Git history. It should support:

- Windows, macOS, and Linux;
- explicit folder selection;
- file-change synchronization with conflict detection;
- local secret references that never upload their values by default;
- local or cloud execution selection;
- resumable workspace state.

### GitHub contract

GitHub remains the source-history and collaboration provider for imported repositories. Runtime execution stays on the selected Amosclaud execution plane. GitHub credentials stay in the control plane, and Sync & Push never force-pushes.

## Delivery phases

### Phase A — usable current deployment

- managed terminal fallback;
- live run/debug status;
- persistent repository schema repair;
- agent help and repository-root fixes;
- GitHub synchronization.

### Phase B — isolated production runtime

- dedicated Docker/Kata/Firecracker execution hosts;
- durable repository volumes;
- workspace scheduler and quotas;
- port-forwarding gateway;
- runtime metrics and logs.

### Phase C — platform control plane

- PostgreSQL and SQLAlchemy migration;
- encrypted secrets authority;
- organization policies;
- MCP connector registry;
- deployment connector interface.

### Phase D — global developer experience

- desktop/CLI launcher;
- local folder synchronization;
- multi-region runtime scheduling;
- Railway, Render, AWS, and GCP release workflows;
- unified production monitoring and rollback.
