# Amosclaud Quickstart

This guide provides three increasingly complete ways to run Amosclaud:

1. deterministic local repository inspection;
2. the local API and Control Plane;
3. the self-hosted stack with Ollama, an execution node, and the Java pod runtime.

Start with the smallest mode that solves your problem. The full stack is not required for `amosclaud-quick`.

## Prerequisites

Required for local development:

- Git;
- Python 3.11 or newer;
- a supported shell: Bash, zsh, PowerShell, or Command Prompt.

Required for self-hosted services and Java pods:

- Docker Engine or Docker Desktop;
- Docker Compose v2;
- at least 4 GB of available memory; 8 GB or more is recommended when running Ollama and Java builds together.

Optional:

- a GitHub account and repository authorization for GitHub-native operations;
- an Ollama-compatible model for model-assisted tasks;
- a separate connected computer for additional execution capacity.

## 1. Install the source checkout

```bash
git clone https://github.com/wamakologeorge-dev/amosclaude-clean.git
cd amosclaude-clean

python3 -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
pip install -e .
```

Confirm the installed command contract:

```bash
amosclaud --help
amosclaud-quick --help
amosclaud-workspace doctor
```

`amosclaud-workspace doctor` reports missing Docker or configuration truthfully. A failed doctor report does not prevent the offline quick-check command from working.

## 2. Get immediate offline repository evidence

```bash
amosclaud-quick . --objective "Find the cause of the failing login tests"
```

Machine-readable evidence:

```bash
mkdir -p .amosclaud
amosclaud-quick . \
  --objective "Inspect authentication and callback handling" \
  --json \
  --output .amosclaud/quickcheck.json
```

This mode does not require an Amosclaud account, API key, hosted model, or network request. It validates supported Python, JSON, YAML, and TOML files, detects unresolved merge markers, and avoids reading common sensitive files.

## 3. Run the local API and web application

Create a development environment file. Never put real secrets into a committed file.

```bash
cp .env.example .env
```

For a local-only start, these values are enough to establish the basic server paths:

```dotenv
ENVIRONMENT=development
DEBUG=true
HOST=127.0.0.1
PORT=8000
AUTH_COOKIE_SECURE=false
DATABASE_URL=sqlite:///./data/amosclaud.db
AUTH_DB_PATH=./data/auth.db
REPOSITORY_STORAGE_PATH=./data/repositories
STORAGE_PATH=./data/storage
AMOSCLAUD_MODEL_URL=http://127.0.0.1:11434
AMOSCLAUD_MODEL=qwen2.5-coder:1.5b
```

Start the application:

```bash
python -m amoscloud_ai.main
```

Verify it from another terminal:

```bash
curl --fail http://127.0.0.1:8000/health
```

Development URLs:

- application: `http://127.0.0.1:8000`;
- OpenAPI: `http://127.0.0.1:8000/docs`;
- Control Plane: `http://127.0.0.1:8000/control-plane` after authentication.

## 4. Start the self-hosted stack

The self-hosted compose file runs the Amosclaud application, an Ollama service, a one-time model pull, persistent data, and an optional connected runner.

```bash
cp .env.example .env
mkdir -p AmosclaudWorkspace

docker compose -f docker-compose.selfhost.yml up -d
```

Check the services:

```bash
docker compose -f docker-compose.selfhost.yml ps
curl --fail http://127.0.0.1:8000/health
```

Follow logs:

```bash
docker compose -f docker-compose.selfhost.yml logs --tail 200 -f app model
```

Stop without deleting persistent volumes:

```bash
docker compose -f docker-compose.selfhost.yml down
```

The first start can take longer because Ollama pulls the configured model. Set a smaller model in `.env` when the host has limited memory:

```dotenv
AMOSCLAUD_MODEL=qwen2.5-coder:1.5b
AMOSCLAUD_WORKSPACE_PATH=./AmosclaudWorkspace
```

## 5. Build the Java pod runtime

```bash
docker build \
  -t amosclaud-java-pod:21 \
  services/java-pod-runtime
```

The image runs as a non-root user and supports:

- Maven, including a repository-owned Maven wrapper;
- a repository-owned Gradle wrapper;
- direct `javac` compilation;
- JAR and WAR artifact collection;
- machine-readable `result.json` or `pipefail.json` evidence.

A production node launcher must enforce the security contract returned by the launch-spec API. Building the image alone does not register a node or grant it repository access.

## 6. Register an execution node

Sign in to the local Amosclaud application and open the Control Plane. Use **Execution nodes → Register execution node** with values such as:

```text
Name: local-java-node
Endpoint: http://host.docker.internal:8098
Capabilities: java-pod,maven,gradle,javac
CPU millicores: 4000
Memory MB: 8192
Disk MB: 51200
```

The equivalent request body is available in [`docs/examples/pipeline-runtime.example.json`](examples/pipeline-runtime.example.json). The runtime API is authenticated and should not be exposed as an anonymous public endpoint.

The node proposer considers:

- node status and heartbeat freshness;
- Java and build-tool capabilities;
- currently leased CPU, memory, disk, and GPU;
- remaining headroom and projected utilization.

Its choice is advisory. Java pod creation rechecks capacity transactionally before creating the lease.

## 7. Create a cooperation pipeline

From the Control Plane:

1. select a repository or the platform workspace;
2. select `inspect`, `build`, `fix`, `deploy`, or `monitor`;
3. enter the objective and branch;
4. leave write approval disabled unless the protected stage is already authorized;
5. create the pipeline;
6. register or connect workers with the required task capabilities.

A `fix` or `deploy` pipeline can run context, inspection, and planning stages before it pauses at the repository-write approval gate. Automatic GitHub triggers never pre-approve that gate.

## 8. Connect GitHub-native triggers

Configure these GitHub Actions repository secrets:

```text
AMOSCLAUD_PIPELINE_URL=https://your-amosclaud-host.example
AMOSCLAUD_GITHUB_PIPELINE_TOKEN=<random-server-side-secret>
```

Configure the same token on the Amosclaud server:

```dotenv
AMOSCLAUD_GITHUB_PIPELINE_TOKEN=<same-random-server-side-secret>
AMOSCLAUD_GITHUB_AUTOMATION_EMAIL=owner@example.com
```

The automation email must identify an existing Amosclaud user. A numeric `AMOSCLAUD_GITHUB_AUTOMATION_USER_ID` can be used instead.

When endpoint secrets are unavailable, the workflow writes local trigger evidence and does not pretend that a remote pipeline was created. See [GitHub Actions](GITHUB_ACTIONS.md) for trigger and permission details.

## 9. Run validation before opening a pull request

```bash
make test
make quality
make build
```

The equivalent explicit commands are:

```bash
python scripts/workspace_task.py test
python scripts/workspace_task.py quality
python scripts/workspace_task.py build
```

For the pipeline-cooperation runtime, run focused tests during development:

```bash
pytest -q \
  tests/test_pipeline_cooperation.py \
  tests/test_execution_nodes.py \
  tests/test_runtime_telemetry.py \
  tests/test_github_native_triggers.py
```

The complete CI suite remains authoritative because it also checks integration, packaging, web assets, security, and compatibility surfaces.

## Troubleshooting

### Docker is missing

Use `amosclaud-quick` and the local Python API first. `amosclaud-workspace doctor` will report `docker_found: false` rather than treating Docker-backed services as ready.

### No eligible Java node

Check node heartbeat, status, build-tool capability, and available resources in the node proposer. A node marked offline or lacking `java`/`java-pod` is intentionally ineligible.

### Model is unavailable

Native repository and pipeline operations should report the model as unavailable without substituting fake output. Start Ollama, verify `AMOSCLAUD_MODEL_URL`, and confirm the configured model exists.

### A fix pipeline is waiting

That is expected when repository writes have not been approved. Inspect the plan and evidence, then approve or reject the protected stages from the Control Plane.

### A Java pod failed

Review PipeFail telemetry. Retryable node failures can release the original lease and reassign the same pod to another compatible node. Compile or test failures remain terminal unless explicitly classified as retryable within the bounded attempt limit.
