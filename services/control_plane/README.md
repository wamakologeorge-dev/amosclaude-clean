# Amosclaud Node.js Control Plane

This service is the private orchestration layer for asynchronous Amosclaud work. It does not replace the existing Python intelligence services or the isolated Docker workspace runtime.

## Responsibilities

- accept authenticated task requests and return immediately;
- persist jobs in BullMQ/Redis so work survives API restarts;
- run a separate worker with bounded concurrency;
- stream task logs through Server-Sent Events;
- coordinate the existing workspace runtime lifecycle;
- execute explicitly allowed local commands without a shell when local mode is enabled;
- watch shared repository folders and enqueue debounced verification tasks;
- synchronize versioned `SKILL.md` files from installed npm packages.

## Security boundary

The API is private and requires `Authorization: Bearer <AMOSCLAUD_CONTROL_PLANE_TOKEN>` on every endpoint except `/live`.

Local command execution is disabled unless `AMOSCLAUD_EXECUTION_MODE=local` is set. The worker:

- runs commands by executable name, never through `shell=true`;
- enforces an executable allowlist;
- rejects absolute paths and workspace traversal;
- resolves symbolic links before selecting a working directory;
- starts child processes with a minimal environment instead of inheriting platform secrets;
- caps command duration;
- runs as an unprivileged container user.

Do not mount the Docker socket, database credentials, model credentials, GitHub App private keys, or public web-service secrets into this service. For public multi-user execution, continue using the existing isolated workspace runtime.

## Start locally

```bash
cp .env.example .env
# Set both private service tokens.
docker compose -f docker-compose.control-plane.yml up --build
```

The API binds to `127.0.0.1:8300` by default in the Compose file.

### Chromebook and ChromeOS

For a native ChromeOS Linux setup that does not require Docker, follow [Run Amosclaud locally on a Chromebook](../../docs/CHROMEOS_LOCAL_DEVELOPMENT.md). The guide installs Node.js 22 with `nvm`, runs Redis inside the Debian environment, starts the API and worker separately, and opens the local health endpoint through Chrome.

## API

Create a command task:

```http
POST /v1/tasks
Authorization: Bearer <private-token>
Content-Type: application/json

{
  "type": "command",
  "workspaceId": "ws_1234567890ab",
  "repositoryId": 42,
  "command": "npm",
  "args": ["test"],
  "cwd": ".",
  "timeoutMs": 300000
}
```

Runtime lifecycle tasks use `runtime.start`, `runtime.stop`, or `runtime.status`.

Inspect or cancel work:

```text
GET  /v1/tasks/{task_id}
GET  /v1/tasks/{task_id}/logs?after=0
GET  /v1/tasks/{task_id}/events?after=0
POST /v1/tasks/{task_id}/cancel
```

Create a watcher:

```http
POST /v1/watchers
Authorization: Bearer <private-token>
Content-Type: application/json

{
  "workspaceId": "ws_1234567890ab",
  "repositoryId": 42,
  "path": "src",
  "command": "npm",
  "args": ["test"],
  "cwd": ".",
  "debounceMs": 1000
}
```

Only one worker replica becomes the watcher leader through a renewable Redis lease. Other worker replicas continue processing normal jobs.

## npm skill packages

An installed npm package can publish Amosclaud instructions without an install script. Add an `amosclaud.skills` field to that package's `package.json`:

```json
{
  "name": "@amosclaud/skills-github",
  "version": "1.0.0",
  "amosclaud": {
    "skills": [
      {
        "id": "github-repair",
        "source": "skills/github-repair/SKILL.md"
      }
    ]
  }
}
```

Then configure and synchronize it:

```bash
export AMOSCLAUD_SKILL_PACKAGES=@amosclaud/skills-github
npm run skills:sync
```

The synchronizer resolves the installed package, validates its manifest, blocks path traversal, verifies that each source stays inside its package, and copies files atomically into `AMOSCLAUD_SKILL_OUTPUT_ROOT`.

## npm supply-chain policy

- dependency versions are exact, not ranges;
- the package is private;
- lifecycle install scripts are forbidden in this package;
- `.npmrc` disables dependency lifecycle scripts by default;
- CI runs syntax tests, path-policy tests, and `npm audit`;
- a generated lockfile should be committed before the first production release and deployments should then switch from `npm install` to `npm ci`.

## Agent framework adapters

The queue and tool contracts are model-neutral. Vercel AI SDK, Mastra, LangGraph.js, or official model SDKs should be added as separate adapter packages behind the same task contract rather than embedded into the orchestration core. This keeps Amosclaud able to select local or cloud models without coupling workspace safety to one framework.
