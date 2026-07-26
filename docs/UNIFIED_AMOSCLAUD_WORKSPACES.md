# Unified Amosclaud developer platform

`wamakologeorge-dev/amosclaude-clean` is the canonical Amosclaud program.
The former `wamakologeorge-dev/Amosclaud1` repository contains a static Command
Center only; its useful dashboard experience is now preserved in
`web/amosclaud-command-center.html` and will be served by the production
platform. The legacy repository can become a migration landing page after this
branch is verified and merged.

## Security boundary

The public FastAPI application does **not** receive a Docker socket and does not
execute an interactive user shell. It owns authentication, repository access,
workspace metadata, and the private provider client.

A separately deployed `workspace_worker` service is the only service allowed to
communicate with a dedicated rootless Docker daemon. The worker API requires a
high-entropy bearer token supplied through a mounted secret file.

Each developer workspace is created with these hard maximums:

- non-root numeric UID and GID;
- 2 CPU cores;
- 4096 MB memory with swap disabled above that limit;
- 512 processes;
- read-only container root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges` enabled;
- writable temporary filesystems marked `noexec`, `nosuid`, and `nodev`;
- only the selected persistent repository and editor-state directories mounted;
- no host Docker socket, database URL, GitHub token, payment credential, or
  Amosclaud service secret injected into the user container;
- no directly published host or public port.

The workspace image is configured by `AMOSCLAUD_WORKSPACE_IMAGE`. Production
should pin the image to an immutable digest after it is built and scanned.

## Persistent storage

The application and worker must mount the same repository storage at different
service paths:

- public API: `REPOSITORY_STORAGE_PATH`;
- workspace worker: `AMOSCLAUD_REPOSITORY_STORAGE_ROOT`.

The worker also receives a separate persistent workspace-state path for
code-server preferences and extensions. Stopping or deleting a container never
removes the repository or its `.git` history.

For one host, these paths may be bind mounts on encrypted local storage. For a
multi-node deployment, use a storage system that preserves POSIX ownership,
locking, and rename semantics. Validate Git operations and file locking before
using a network filesystem in production.

## Private provider configuration

Public Amosclaud API:

```text
AMOSCLAUD_WORKSPACE_PROVIDER_URL=http://workspace-worker:8092
AMOSCLAUD_WORKSPACE_PROVIDER_TOKEN_FILE=/run/secrets/workspace_worker_token
AMOSCLAUD_WORKSPACE_PROVIDER_TIMEOUT=20
```

Workspace worker:

```text
AMOSCLAUD_WORKSPACE_WORKER_TOKEN_FILE=/run/secrets/workspace_worker_token
DOCKER_HOST=unix:///run/amosclaud/docker.sock
AMOSCLAUD_WORKSPACE_IMAGE=ghcr.io/coder/code-server:4.96.4
AMOSCLAUD_WORKSPACE_USER=1000:1000
AMOSCLAUD_WORKSPACE_STORAGE_ROOT=/var/lib/amosclaud/workspaces
AMOSCLAUD_REPOSITORY_STORAGE_ROOT=/var/lib/amosclaud/repositories
AMOSCLAUD_WORKSPACE_MAX_CPU=2
AMOSCLAUD_WORKSPACE_MAX_MEMORY_MB=4096
AMOSCLAUD_WORKSPACE_MAX_PIDS=512
```

Use `deploy/workspace-worker/docker-compose.yml` only on a dedicated sandbox
host connected to a rootless Docker daemon. Do not mount a privileged system
Docker socket into the public platform container.

## Workspace lifecycle

1. An authenticated developer creates a workspace for a repository they can
   modify.
2. Amosclaud records the requested branch and bounded machine profile.
3. Starting the workspace calls the private provider.
4. The worker validates identifiers and storage paths, creates the isolated
   container, and returns status and gateway URLs.
5. The public application stores only non-secret runtime evidence.
6. Stop and restart operations are forwarded to the worker.
7. Delete removes the container but preserves repository and Git history.

## Editor and terminal

The workspace image runs code-server. Its integrated terminal is powered by the
browser editor and executes as the same restricted non-root user inside the
workspace container.

The worker does not publish code-server directly. Production must place an
authenticated Amosclaud gateway in front of editor and terminal traffic. The
configured editor URL must use HTTPS and terminal WebSocket URLs must use WSS.
The gateway must verify the Amosclaud session and workspace ownership on every
connection before proxying to the isolated workspace.

## Repository convergence sequence

1. Merge and deploy the GitHub organization synchronization PR.
2. Verify this workspace-control branch and open its draft PR.
3. Deploy the private workspace worker and shared persistent storage.
4. Enable the authenticated editor/terminal gateway.
5. Change `Amosclaud1` into a read-only migration page pointing developers to
   the canonical platform and repository.
6. Archive the legacy repository only after links, Pages, and documentation
   have been migrated and verified.
