# Unified Amosclaud Platform

## Repository decision

`wamakologeorge-dev/amosclaude-clean` is the canonical Amosclaud product repository. It contains the web application, autonomous engine, repository platform, GitHub integration, Command Center, cloud workspace control plane, and dedicated workspace-runtime service.

`wamakologeorge-dev/Amosclaud1` was a small static Command Center dashboard. Its useful architecture view, execution path, and safety gates are now integrated into `web/command-center.html`. It remains unchanged only as a recovery source until the unified pull request passes every required check. After that, the old repository can be converted to a read-only redirect notice instead of running a second Amosclaud program.

## One program, separated trust zones

Combining the source repositories does **not** mean running arbitrary user code inside the public web container. The unified repository builds several deliberately separated services:

```text
www.amosclaud.com
└─ Control plane
   ├─ authentication and sessions
   ├─ native repositories and Git history
   ├─ autonomous agent and verification
   ├─ GitHub organization publishing
   ├─ signed GitHub webhook synchronization
   ├─ server-managed cloud policy
   └─ short-lived workspace terminal tickets

Private execution host
└─ Workspace runtime
   ├─ Docker API access
   ├─ one non-root container per active repository workspace
   ├─ PTY/WebSocket bridge
   ├─ CPU, memory, PID, capability, filesystem, and network limits
   └─ shared persistent repository volume
```

The public web service never mounts `/var/run/docker.sock`. The runtime service does not receive the platform database, billing secrets, authentication cookies, model credentials, or GitHub OAuth token.

## Unified developer flow

1. A signed-in developer opens a native Amosclaud repository.
2. The existing web workspace provides files, branches, commits, issues, pull requests, chat, and autonomous operations.
3. The developer opens the **Terminal** tab.
4. Amosclaud authorizes repository write access and starts the repository's isolated container.
5. The control plane issues a nonce-bound HMAC ticket that expires after two minutes.
6. Xterm.js opens a WebSocket directly to the workspace-runtime endpoint.
7. The runtime validates the browser origin, ticket signature, expiry, and replay state.
8. A host PTY bridges the socket to `docker exec` as the `developer` user in `/workspace`.
9. Files and `.git` history remain on persistent storage when the container stops.
10. Platform changes push to the authorized GitHub user or organization.
11. GitHub sends a signed push webhook back to Amosclaud.
12. Amosclaud fast-forwards only when the local workspace is clean and not ahead or diverged.

## Resource and network policy

The server-managed organization policy fixes the default upper limits at:

- 2 CPU cores
- 4096 MB RAM
- 512 processes
- 30-minute idle timeout
- non-root `developer` user
- no container network
- no internal platform mesh access
- no project-level override endpoint

The runtime additionally drops every Linux capability, enables `no-new-privileges`, and uses a read-only root filesystem. The only durable writable mount is the selected repository.

## Editor choice

Amosclaud keeps its existing custom repository file tree and full-screen editor because those components already use the native repository API and authorization model. Xterm.js is added only for terminal rendering. This avoids embedding a second authentication system through code-server while still providing a real browser shell.

A future code-server deployment may be added behind the same workspace ticket and container boundary, but it must not bypass repository authorization or receive a permanent public URL.

## GitHub lifecycle

The same canonical repository implementation supports:

- creating a new GitHub repository under the connected user;
- creating under an authorized GitHub organization;
- publishing an existing native workspace;
- using a credential only for the Git network operation;
- restoring a public credential-free `origin` URL afterward;
- receiving HMAC-SHA256 signed push events;
- recording webhook evidence;
- pulling back with fast-forward-only rules.

No SSH private key, GitHub Actions SSH deployment, or ephemeral `/home/runner/work/...` path is required.

## Production requirements

The control plane needs:

```text
AMOSCLAUD_WORKSPACE_RUNTIME_URL
AMOSCLAUD_WORKSPACE_PUBLIC_URL
AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN
GITHUB_CLIENT_ID
GITHUB_CLIENT_SECRET
GITHUB_REPOSITORY_CALLBACK_URL
GITHUB_TOKEN_ENCRYPTION_KEY
GITHUB_APP_WEBHOOK_SECRET
```

The execution host needs the variables in `services/workspace_runtime/.env.example`, Docker, the built workspace image, and the persistent repository volume.

The terminal public endpoint must support HTTPS and WebSocket upgrades. The runtime's control API should stay private. Firewall rules should allow the public terminal route while restricting bearer-authenticated workspace lifecycle endpoints to the Amosclaud control plane.

## Completion gate

The repository transition is complete only when:

- focused unified-workspace tests pass;
- the full repository test suite and required GitHub workflows are green;
- Docker image checks pass;
- security analysis is green or every finding is resolved with evidence;
- the unified application is deployed with a reachable workspace-runtime service;
- a real repository can start, open a terminal, preserve a file after stop/start, push to GitHub, and safely receive the signed push back;
- the old Amosclaud1 repository is replaced by a redirect/archive notice in a separate reviewed change.

Until those conditions are met, the unification pull request remains a draft and the old repository remains available as a recovery source.
