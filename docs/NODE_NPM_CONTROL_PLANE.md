# Node.js and npm Control-Plane Architecture

## Decision

Amosclaud uses Node.js as a private asynchronous orchestration layer and npm as the controlled JavaScript package and skill distribution layer. Python remains responsible for existing AI reasoning, repository analysis, repair logic, and the isolated workspace runtime.

## Service topology

```text
Amosclaud.com / Python API
          │ authenticated private task request
          ▼
Node.js Fastify control plane
          │
          ├── BullMQ task queue ───── Redis
          │                              │
          │                              ├── task state and bounded logs
          │                              ├── cancellation flags
          │                              └── watcher registry and leader lease
          │
          ▼
Node.js workers
          ├── local trusted-workspace executor (Execa, no shell)
          ├── Chokidar watcher leader
          ├── npm skill synchronizer
          └── lifecycle client ───────► isolated Python/Docker runtime
```

The public Python web process does not mount a Docker socket. The Node control plane also does not mount one. Existing terminal and untrusted project-container execution remain inside `services/workspace_runtime`.

## Asynchronous task contract

The initial queue supports:

- `command`: run an allowlisted executable in one repository directory;
- `runtime.start`: start the existing isolated workspace container;
- `runtime.stop`: stop it without deleting persistent repository storage;
- `runtime.status`: read its current state.

The API returns a BullMQ job identifier immediately. Clients can poll task state, fetch bounded logs, subscribe to Server-Sent Events, or request cancellation.

## Local workspace execution

Local execution is intended for a private local-first installation or a dedicated worker host with one repository-storage mount. It is not a replacement for sandboxed public execution.

Controls include:

1. disabled by default;
2. executable allowlist;
3. no shell interpolation;
4. relative working directories only;
5. real-path and symbolic-link containment checks;
6. minimal inherited environment;
7. output stored in bounded Redis logs;
8. timeout and cancellation support;
9. unprivileged container identity;
10. no Docker socket or internal platform secrets.

## File watching

Watcher definitions are persistent Redis records. A renewable Redis lease elects one worker as the watcher leader, preventing every worker replica from triggering duplicate builds. Chokidar ignores dependency, VCS, cache, and build-output folders and debounces change bursts before enqueuing a normal command task.

## npm as the Amosclaud tool distributor

npm serves four distinct purposes:

### Runtime libraries

Fastify supplies the private API, BullMQ and Redis supply durable work distribution, Chokidar normalizes file events, Execa runs commands without shell interpolation, and Zod validates every task and package manifest.

### Agent framework adapters

Vercel AI SDK, Mastra, LangGraph.js, and model-specific SDKs belong in optional adapter packages. They should implement Amosclaud's stable task/tool interface rather than control workspace permissions directly. The orchestration core therefore remains model-neutral.

### Versioned skills

An npm package can declare `amosclaud.skills` metadata pointing to one or more instruction files. `npm run skills:sync` validates and atomically extracts those files into the configured local skills directory. This enables semantic versioning, rollback, and reproducible distribution without granting package install scripts access to the machine.

### Supply-chain enforcement

The service uses exact direct dependency versions, forbids package lifecycle scripts in its own manifest, disables dependency install scripts through `.npmrc`, validates package paths before copying skills, and audits installed dependencies in CI.

Before production release, generate and commit `package-lock.json`, review it, and change deployment installs to `npm ci`.

## Deployment sequence

1. Deploy Redis with durable append-only storage.
2. Deploy one or more Node worker replicas on a private network.
3. Mount the canonical repository storage only into workers that need local mode.
4. Deploy the Fastify API without public exposure.
5. Configure the same long random control-plane bearer token in the Python caller and Node API.
6. Configure the existing workspace-runtime URL and token for lifecycle tasks.
7. Enable watchers only where the repository volume is shared.
8. Install approved npm skill packages and run the skill synchronizer.
9. Add framework-specific agent adapters one at a time behind the stable queue contract.

## Next integration slice

The next repository change should add a small authenticated Python client that submits long-running autonomous operations to this Node queue and stores the returned task ID in the existing operation bucket. The current synchronous Python routes can then remain compatible while gradually moving builds, tests, and deployments onto durable workers.
