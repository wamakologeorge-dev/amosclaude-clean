# Run Amosclaud locally on a Chromebook

ChromeOS can run the Amosclaud Node.js control plane inside its sandboxed Debian Linux development environment. This setup is intended for local development and testing. It does not replace the separate isolated workspace runtime required for public multi-user execution.

## 1. Enable the Linux development environment

1. Open **ChromeOS Settings**.
2. Go to **Advanced** > **Developers**.
3. Select **Turn on** next to **Linux development environment**.
4. Allocate enough storage for repositories, npm packages, logs, and build output. A practical starting point is 10–20 GB.
5. Open the **Terminal** application after setup completes.

Keep Amosclaud repositories inside the Linux home directory rather than a shared ChromeOS folder. Linux-native storage provides better permissions, file-watching behavior, and build performance.

## 2. Install Git, build tools, and Redis

Update the Debian environment and install the required system packages:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git curl build-essential redis-server ca-certificates
```

Start Redis and confirm that it responds:

```bash
sudo service redis-server start
redis-cli ping
```

The expected response is:

```text
PONG
```

Redis provides the durable BullMQ queue used by the Amosclaud API and worker.

## 3. Install Node.js 22 with nvm

The control plane requires Node.js 22 or newer and npm 10 or newer. Install `nvm`, then install Node.js 22:

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
source "$HOME/.nvm/nvm.sh"
nvm install 22
nvm use 22
nvm alias default 22
```

Verify the runtime:

```bash
node --version
npm --version
```

The repository includes `services/control_plane/.nvmrc`, so future sessions can select the correct version with:

```bash
nvm use
```

## 4. Clone Amosclaud

```bash
cd ~
git clone https://github.com/wamakologeorge-dev/amosclaude-clean.git
cd amosclaude-clean
git checkout agent/node-control-plane-foundation
```

After the pull request is merged, use `main` instead of the feature branch.

## 5. Configure the Node.js control plane

Enter the service directory and install its exact direct dependencies:

```bash
cd services/control_plane
npm install
```

The service-level `.npmrc` disables dependency lifecycle scripts by default.

Create local storage directories:

```bash
mkdir -p "$HOME/.local/share/amosclaud/repositories"
mkdir -p "$HOME/.local/share/amosclaud/skills"
```

Copy the environment template:

```bash
cp .env.example .env
```

Generate a private API token:

```bash
node -e "console.log(require('node:crypto').randomBytes(32).toString('hex'))"
```

Edit `.env` and use local Chromebook values similar to these:

```env
AMOSCLAUD_CONTROL_PLANE_HOST=0.0.0.0
AMOSCLAUD_CONTROL_PLANE_PORT=8300
AMOSCLAUD_CONTROL_PLANE_TOKEN=<paste-the-generated-token>
AMOSCLAUD_REDIS_URL=redis://127.0.0.1:6379/0
AMOSCLAUD_TASK_QUEUE=amosclaud-agent-tasks
AMOSCLAUD_WORKER_CONCURRENCY=2

AMOSCLAUD_EXECUTION_MODE=local
AMOSCLAUD_REPOSITORY_STORAGE_ROOT=/home/<linux-username>/.local/share/amosclaud/repositories
AMOSCLAUD_ALLOWED_COMMANDS=git,npm,npx,pnpm,yarn,node,python,python3,pytest,uv,ruff,mypy,make,go,cargo
AMOSCLAUD_MAX_COMMAND_TIMEOUT_MS=900000

AMOSCLAUD_WORKSPACE_RUNTIME_URL=
AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN=

AMOSCLAUD_WATCHERS_ENABLED=true
AMOSCLAUD_WATCHER_RECONCILE_MS=10000
AMOSCLAUD_SKILL_PACKAGES=
AMOSCLAUD_SKILL_OUTPUT_ROOT=/home/<linux-username>/.local/share/amosclaud/skills
```

Find the Linux username with:

```bash
whoami
```

Replace `<linux-username>` with that value. Do not place real tokens in Git or commit the `.env` file.

The workspace runtime URL and token may remain empty when testing only local command tasks. Container-backed browser terminals require a separately deployed Docker-capable workspace runtime.

## 6. Start the API and worker

Open two Terminal windows or tabs.

In the first terminal:

```bash
cd ~/amosclaude-clean/services/control_plane
source "$HOME/.nvm/nvm.sh"
nvm use
npm start
```

In the second terminal:

```bash
cd ~/amosclaude-clean/services/control_plane
source "$HOME/.nvm/nvm.sh"
nvm use
npm run worker
```

The API and worker are separate processes by design. Restarting the API does not discard queued jobs because Redis retains task state.

## 7. Open the local service in Chrome

Open this address in the Chromebook's normal Chrome browser:

```text
http://localhost:8300/live
```

A healthy API returns an `ok` response. ChromeOS normally forwards Linux development ports to `localhost`. If the page does not open, add port `8300` under the Linux development environment's **Port forwarding** settings.

The control plane is an authenticated API, not a public dashboard. Protected routes require:

```http
Authorization: Bearer <AMOSCLAUD_CONTROL_PLANE_TOKEN>
```

Test a protected endpoint from the Linux terminal:

```bash
set -a
source .env
set +a

curl \
  -H "Authorization: Bearer $AMOSCLAUD_CONTROL_PLANE_TOKEN" \
  http://localhost:8300/v1/tasks/not-a-real-task
```

An authenticated `404` response proves that the API accepted the token and attempted to find the task.

## 8. Prepare a local repository workspace

The worker maps a numeric repository ID to a folder under `AMOSCLAUD_REPOSITORY_STORAGE_ROOT`. For repository ID `1`:

```bash
mkdir -p "$HOME/.local/share/amosclaud/repositories/1"
cd "$HOME/.local/share/amosclaud/repositories/1"
git clone https://github.com/example/example.git .
```

Then a task can safely use `repositoryId: 1` and a relative `cwd`. The worker rejects absolute working directories, `..` traversal, and symbolic-link escapes.

## 9. Validate the installation

Run the service checks:

```bash
cd ~/amosclaude-clean/services/control_plane
npm run check
```

This validates:

- exact direct dependency versions;
- npm supply-chain policy;
- JavaScript syntax;
- command allowlisting;
- secret isolation;
- path traversal and symbolic-link protection.

## Chromebook operating notes

- Keep the Chromebook connected to power during long builds.
- ChromeOS may pause the Linux container when the device sleeps; Redis, the API, and the worker must be restarted after a container shutdown.
- Start with worker concurrency `2` on lower-memory Chromebooks.
- Use the Linux home directory for active repositories and copy only finished artifacts to shared ChromeOS folders.
- Do not expose port `8300` to untrusted networks. The service is a private control plane even though it uses bearer authentication.
- Docker support varies inside ChromeOS Linux. The local Node control plane works with native Redis, but the isolated workspace runtime should run on a separate Docker-capable machine when Docker is unavailable.
