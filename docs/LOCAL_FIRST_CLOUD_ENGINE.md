# Amosclaud Self-Sovereign Local Cloud Engine

This service provides a local control plane that continues to function without Google, GitHub, Railway, Render, or any other identity or hosting provider.

## What is implemented

- **Independent local authority:** first startup creates a 48-byte bearer token, stores only a PBKDF2 hash, and protects state files with owner-only permissions.
- **Folder-first workspaces:** existing local directories are registered directly. No hosted workspace container or external account is required.
- **Bounded autonomous operations:** the API exposes a fixed action catalog instead of arbitrary shell execution. Every write-capable or deployment action requires an exact typed confirmation.
- **Local production path:** Docker image builds and Docker Compose deployments run on the user-owned machine or private server.
- **Offline operation:** workspace registration, authorization, inspection, verification, and local deployment do not require internet connectivity.
- **Zero provider lock-in:** Railway, Render, and public clouds remain optional deployment targets rather than the root control plane.

## Start locally

```bash
python scripts/run_local_cloud.py
```

The first run prints a one-time local authority token. Open `http://127.0.0.1:8765` and use that token.

The plaintext token is never written to disk. Losing it requires local access to rotate or reinitialize the authority state.

## Register a folder

```bash
curl -X POST http://127.0.0.1:8765/v1/workspaces \
  -H "Authorization: Bearer $AMOSCLAUD_LOCAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"my-project","path":"/absolute/path/to/project"}'
```

Set `AMOSCLAUD_LOCAL_ALLOWED_ROOTS` to an OS path-separated list when the service must be restricted to specific parent directories.

## Execute a bounded action

First list workspaces and actions. To run `verify_python`, send the exact confirmation string returned by this rule:

```text
RUN <workspace_id> verify_python
```

```bash
curl -X POST http://127.0.0.1:8765/v1/jobs \
  -H "Authorization: Bearer $AMOSCLAUD_LOCAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id":"ws_REPLACE_ME",
    "action":"verify_python",
    "confirmation":"RUN ws_REPLACE_ME verify_python"
  }'
```

## Security boundary

The service binds to loopback by default. It has no arbitrary command route, no external identity dependency, and no cloud credential requirement. Mounting the Docker socket grants host-level container control; only use the Compose profile on a private, trusted machine.

## Next integration steps

1. Add provider adapters that consume the same immutable deployment plan for Railway, Render, or a private host.
2. Persist job history in SQLite so restarts retain evidence.
3. Add encrypted local secret vault support backed by the OS keychain or a user-managed master key.
4. Connect the main Amosclaud web dashboard to this local API through an explicit pairing flow.
