# Amosclaud Workspace Runtime

This service is the isolated execution plane for browser terminals and cloud workspaces. It belongs in the unified `amosclaude-clean` repository, but it must run on a different host or service from the public Amosclaud web process.

## Boundary

```text
Browser workspace
  ├─ HTTPS → Amosclaud control plane
  │            ├─ account and repository authorization
  │            ├─ persistent workspace record
  │            └─ two-minute signed terminal ticket
  └─ WSS ticket → workspace runtime
                  └─ PTY → non-root project container
```

Only the workspace-runtime service mounts the Docker socket. The public API, authentication service, billing service, PostgreSQL, Redis, and model services do not expose their networks or credentials to a project container.

## Container policy

Every project container is created with these upper bounds:

- user: `developer` (UID/GID 1000 by default)
- CPU: maximum 2 cores
- memory and memory+swap: maximum 4096 MB
- processes: maximum 512
- Linux capabilities: all dropped
- `no-new-privileges`: enabled
- root filesystem: read-only
- writable mounts: the one repository at `/workspace`, temporary `/tmp`, and a small user cache
- network: `none` by default

The runtime mounts the canonical numeric repository directory. The normal web editor, Git operations, autonomous agent, and terminal therefore operate on one persistent file tree and one `.git` history.

## Build and start

Build the non-root project image first:

```bash
docker compose -f docker-compose.workspace-runtime.yml --profile build build workspace-base
```

Then create a real service token and start the execution plane:

```bash
cp services/workspace_runtime/.env.example services/workspace_runtime/.env
# Fill AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN before continuing.
docker compose --env-file services/workspace_runtime/.env \
  -f docker-compose.workspace-runtime.yml up -d workspace-runtime
```

The Compose file binds the API to loopback by default. In production, publish it through an authenticated private load balancer or reverse proxy with HTTPS/WSS. Do not expose the bearer-authenticated control endpoints directly to the public internet.

## Control-plane variables

Set these on the primary Amosclaud API service:

```text
AMOSCLAUD_WORKSPACE_RUNTIME_URL=https://private-runtime.example
AMOSCLAUD_WORKSPACE_PUBLIC_URL=https://terminal.amosclaud.com
AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN=<same random service token>
```

`AMOSCLAUD_WORKSPACE_PUBLIC_URL` is placed into short-lived browser terminal tickets. The runtime independently checks the WebSocket `Origin` header against `AMOSCLAUD_WORKSPACE_ALLOWED_ORIGINS` and rejects ticket replay.

## Persistent storage

Mount the same network-attached repository volume in both services:

```text
Control plane REPOSITORY_STORAGE_PATH       → repositories/<numeric-id>
Runtime AMOSCLAUD_REPOSITORY_STORAGE_ROOT   → repositories/<numeric-id>
```

The host paths can differ, but they must refer to the same durable files. A stopped or replaced container must never remove the repository volume. `AMOSCLAUD_WORKSPACE_DELETE_STORAGE` defaults to `false` for this reason.

## Network access

`AMOSCLAUD_WORKSPACE_NETWORK=none` is the default. It prevents project commands from reaching the public internet and internal platform services. A later egress proxy may be added for package installation, but it must use an allowlist and must never attach project containers to the database, authentication, billing, model, or control-plane networks.

## Operational checks

- `GET /health` proves that the service token exists and Docker answers.
- Amosclaud's Command Center classifies the runtime as `operational`, `unreachable`, or `not_configured` from that probe.
- `POST /v1/maintenance/stop-idle` stops containers whose persistent activity marker exceeds the configured timeout.
- Stopping a workspace preserves files and Git history.
