# Amosclaud Cloud Workspace Runtime

This service is the isolated execution plane for the Amosclaud browser terminal. It lives in the unified `amosclaude-clean` repository, but it must run on a separate Docker-capable host from the public Amosclaud web process.

## Architecture

```text
Browser repository workspace
  ├─ HTTPS → Amosclaud control plane
  │            ├─ account and repository authorization
  │            ├─ Doctor / Fixer / Autonomous / Underground agent hub
  │            ├─ persistent workspace records
  │            └─ two-minute, single-use, session-bound terminal ticket
  └─ WSS ticket → workspace runtime
                   └─ PTY → tmux → non-root project container
```

The terminal and agent hub share the same selected repository context. Agent requests still pass through the Amosclaud control plane; the browser never receives model credentials, runtime bearer tokens, Docker access, or internal service credentials.

Only the workspace-runtime service mounts the Docker socket. The public API, authentication service, billing service, PostgreSQL, Redis, and model services do not expose their networks or credentials to project containers.

## Terminal capabilities

The complete terminal supports:

- up to eight named browser terminal tabs;
- two visible split panes;
- persistent `tmux` sessions that survive browser reconnects;
- Bash, POSIX shell, and Python REPL profiles;
- PTY resize messages from the browser;
- terminal search, copy, clear, and transcript export;
- repository-aware prompt and Git branch indicator;
- 10,000 lines of browser scrollback;
- a short-lived signed WebSocket ticket bound to workspace, user, terminal ID, and profile;
- detected **Run app** and **Debug** controls;
- separate GitHub Pull and Push controls plus a safe **Sync & Push** action;
- four terminal feature cells for **Ports**, **Problems**, **Connectors**, and **Network**.

### Workspace feature cells

- **Ports** scans local listening TCP ports with `ss`, `netstat`, or `lsof`. It does not silently publish a project port to the internet. Any future forwarding remains controlled by server policy.
- **Problems** runs `git diff --check` and the repository's detected lint, type-check, and test commands, then directs unresolved failures to Amosclaud Doctor.
- **Connectors** shows whether the repository is Amosclaud-native or GitHub-backed and opens the governed terminal agent hub. GitHub credentials remain outside the project container.
- **Network** reports the workspace network mode and can inspect interfaces, routes, DNS, and outbound HTTPS behavior without exposing internal platform networks.

The `amos` helper exposes the same workflow inside the shell:

```text
amos run
amos debug
amos ports
amos problems
amos connectors
amos network
```

For GitHub-backed repositories, **Sync & Push** commits authorized working-tree changes, fetches the remote, safely rebases when required, and pushes without force. A rebase conflict is aborted and returned to the user for resolution.

The adjacent support hub provides four governed roles:

- **Amosclaud Doctor** — diagnosis only, no repository writes;
- **Amosclaud Fixer** — bounded repair when changes are explicitly authorized;
- **Amosclaud Autonomous Agent** — complete engineering work with verification;
- **Amosclaud Underground Fixer** — safe escalation for stubborn failures, without force push, protected-branch bypass, or unverified success claims.

Recent terminal output is attached only when the user leaves that option selected. The control plane clips it and redacts likely tokens, passwords, API keys, and bearer credentials before sending it to an agent.

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

The runtime mounts the canonical numeric repository directory. The normal web editor, Git operations, autonomous agent, terminal, and support hub therefore operate on one persistent file tree and one `.git` history.

## Build and start

Build the non-root project image first:

```bash
docker compose -f docker-compose.workspace-runtime.yml --profile build build workspace-base
```

Create a real service token and start the execution plane:

```bash
cp services/workspace_runtime/.env.example services/workspace_runtime/.env
# Fill AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN before continuing.
docker compose --env-file services/workspace_runtime/.env \
  -f docker-compose.workspace-runtime.yml up -d workspace-runtime
```

The Compose stack binds to loopback by default. For cloud use, put the runtime behind a private HTTPS/WSS reverse proxy or authenticated load balancer. Do not expose the bearer-authenticated lifecycle endpoints directly to the public internet.

## Connect the Amosclaud cloud control plane

Set these variables on the main Amosclaud service, including a Railway-hosted control plane:

```text
AMOSCLAUD_WORKSPACE_RUNTIME_URL=https://private-runtime.example
AMOSCLAUD_WORKSPACE_PUBLIC_URL=https://terminal.amosclaud.com
AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN=<same long random service token>
```

- `AMOSCLAUD_WORKSPACE_RUNTIME_URL` is used server-to-server for health, start, stop, and status operations.
- `AMOSCLAUD_WORKSPACE_PUBLIC_URL` is placed into short-lived browser WebSocket tickets.
- `AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN` must match the runtime service token and must never be exposed to browser JavaScript.

The runtime independently checks the WebSocket `Origin` header against `AMOSCLAUD_WORKSPACE_ALLOWED_ORIGINS`, verifies the signature, rejects expired tickets, and rejects ticket replay.

A managed application platform can host the public Amosclaud control plane, but the terminal execution plane still needs a Docker-capable host with durable storage. The control plane and runtime may be on different providers as long as the private API, public WSS endpoint, shared token, and repository storage are configured correctly.

## Persistent storage

Mount the same durable repository storage in both services:

```text
Control plane REPOSITORY_STORAGE_PATH       → repositories/<numeric-id>
Runtime AMOSCLAUD_REPOSITORY_STORAGE_ROOT   → repositories/<numeric-id>
```

The host paths can differ, but they must refer to the same durable files. A stopped or replaced container must never remove the repository volume. `AMOSCLAUD_WORKSPACE_DELETE_STORAGE` defaults to `false` for this reason.

## Network access

The project-container network remains `none`. This prevents project commands from reaching the public internet and internal platform services. The Network feature cell truthfully displays that policy and shows the resulting diagnostics. Package downloads should later use a separately designed allowlisted egress proxy; project containers must never join the database, authentication, billing, model, or control-plane networks.

## Operational checks

- `GET /live` proves the runtime web service is alive.
- authenticated `GET /health` proves the service token exists and Docker answers.
- Amosclaud classifies the runtime as `operational`, `unreachable`, or `not_configured` from that probe.
- `POST /v1/maintenance/stop-idle` stops containers whose persistent activity marker exceeds the configured timeout.
- stopping a workspace preserves files, Git history, and the cloud-workspace database record.
