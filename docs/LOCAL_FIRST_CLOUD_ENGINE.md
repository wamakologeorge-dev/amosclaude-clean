# Amosclaud Self-Sovereign Local Cloud Engine

This service provides a local control plane that continues to function without Google, GitHub, Railway, Render, or another identity or hosting provider.

## Implemented capabilities

- **Independent local authority:** first startup creates a 48-byte bearer token, stores only a PBKDF2 hash, and protects state files with owner-only permissions.
- **Folder-first workspaces:** existing local directories are registered directly. No hosted workspace container or external account is required.
- **Bounded autonomous operations:** the API exposes a fixed action catalog instead of arbitrary shell execution. Every write-capable or deployment action requires an exact typed confirmation.
- **Agentic build guard:** failed Python verification or Docker builds can be sent to a configured local model, which may return only a bounded unified diff. Amosclaud validates the patch and retries up to three total attempts.
- **Local production path:** Docker image builds and Docker Compose deployments run on the user-owned machine or private server.
- **Offline operation:** workspace registration, authorization, inspection, verification, and local deployment do not require internet connectivity.
- **Zero provider lock-in:** Railway, Render, and public clouds remain optional deployment targets rather than the root control plane.

## Start the local daemon

```bash
python scripts/run_local_cloud.py
```

The first run prints a one-time local authority token. Open `http://127.0.0.1:8765` and use that token. The plaintext token is never written to disk.

## Register a folder

```bash
curl -X POST http://127.0.0.1:8765/v1/workspaces \
  -H "Authorization: Bearer $AMOSCLAUD_LOCAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"my-project","path":"/absolute/path/to/project"}'
```

Set `AMOSCLAUD_LOCAL_ALLOWED_ROOTS` to an OS path-separated list when the service must be restricted to specific parent directories.

## Configure the local build-guard model

The guard expects an OpenAI-compatible chat-completions endpoint. Loopback is required by default.

```bash
export AMOSCLAUD_LOCAL_MODEL_URL=http://127.0.0.1:11434/v1/chat/completions
export AMOSCLAUD_LOCAL_MODEL_NAME=your-local-coding-model
```

On Windows PowerShell:

```powershell
$env:AMOSCLAUD_LOCAL_MODEL_URL = "http://127.0.0.1:11434/v1/chat/completions"
$env:AMOSCLAUD_LOCAL_MODEL_NAME = "your-local-coding-model"
```

## Instant Windows commands

Run these from the repository root:

```bat
amosclaud test
amosclaud guard-test
amosclaud build
amosclaud guard-build
amosclaud serve
```

To target another folder:

```bat
amosclaud guard-test --workspace "C:\projects\my-app"
```

The commands have fixed meanings:

- `test` compiles Python and runs pytest when a `tests` folder exists.
- `guard-test` runs the same verification and allows up to two model patches across three verification attempts.
- `build` runs a normal local Docker build.
- `guard-build` runs the Docker build through the three-attempt repair loop.
- `serve` starts the loopback FastAPI daemon.

The launcher invokes `python -m scripts.agent_guard_cli` from the repository root so local package imports resolve consistently. There is deliberately no command that accepts arbitrary shell text.

## API guarded actions

The FastAPI action catalog also includes:

```text
guarded_verify_python
guarded_docker_build
```

Each API request still requires the exact confirmation form:

```text
RUN <workspace_id> <action>
```

## Build-guard safety contract

The backend owns the test or Docker command. The model cannot provide a shell command. Model output must be a unified diff that edits existing regular source files.

The guard rejects:

- file creation, deletion, or renaming;
- absolute paths, traversal segments, and any symlink component;
- `.git`, `.hg`, `.svn`, `.amosclaud`, and `amosclaud_vault`;
- `.env` files, databases, private keys, and certificates;
- patches larger than the configured bounded size;
- model output containing prose or Markdown fences.

If the third verification attempt still fails, every model-touched file is restored to its pre-loop content. Successful repairs remain in the local working tree for human review and an explicit Git commit.

## Version control and runtime separation

Git remains the historical ledger. The local daemon performs verification, container builds, and runtime execution directly from the local workspace. A remote repository outage therefore does not stop local tests or local deployment operations. Git commits and pushes remain explicit operations and are not silently performed by the build guard.

## Security boundary

The service binds to loopback by default. It has no arbitrary command route, no external identity dependency, and no cloud credential requirement. Mounting the Docker socket grants host-level container control; only use the Compose profile on a private, trusted machine.

## Remaining platform work

1. Persist job and watcher evidence in SQLite so restarts retain the operational history.
2. Add an encrypted local secrets vault backed by the OS keychain or a user-managed master key.
3. Add provider adapters that consume the same immutable deployment plan for Railway, Render, or a private host.
4. Connect the main Amosclaud web dashboard to this local API through an explicit pairing flow.
