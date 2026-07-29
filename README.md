[![Amosclaud Autonomous Fixer](https://github.com/wamakologeorge-dev/amosclaude-clean/actions/workflows/amosclaud-fixer.yml/badge.svg)](https://github.com/wamakologeorge-dev/amosclaude-clean/actions/workflows/amosclaud-fixer.yml)
# Amosclaud Workflow Results Dashboard

This dashboard is the real results area for Amosclaud Autonomous jobs.

It gives users a Railway-style place to:

- create projects;
- configure repository URL and workspace root path;
- change build, start, test, or verification commands;
- define the output path that should become an artifact;
- add environment variables and encrypted secrets;
- run a workflow and inspect real process logs and exit codes;
- open generated artifact manifests;
- configure and verify custom domains with a DNS TXT record.

## Run it

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8100
```

Open:

```text
http://localhost:8100
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --reload --port 8100
```

## Storage

By default, the dashboard creates:

```text
data/
├── dashboard.db
├── .dashboard.key
├── projects/
└── artifacts/
```

Set `AMOSCLAUD_DASHBOARD_DATA=/data/workflow-dashboard` in production.

For a stable encryption key, generate one:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Then set:

```env
AMOSCLAUD_DASHBOARD_KEY=the-generated-key
```

Never rotate this key without re-encrypting existing secrets.

## Connect Amosclaud Autonomous

After the agent creates or selects a project:

1. Update project settings with `PATCH /api/projects/{project_id}`.
2. Save variables using `PUT /api/projects/{project_id}/variables/{name}`.
3. Start the approved job using `POST /api/projects/{project_id}/runs`.
4. Store the returned run ID in the conversation.
5. Link the user to `/?project={project_id}` or add project selection in the existing Amosclaud UI.
6. Display logs from `GET /api/runs/{run_id}`.

A production executor should replace the synchronous `subprocess.run` block with the existing Amosclaud Task Router or Server Station. The API must enqueue the job, return immediately, and stream or poll run state.

## Security work required before public deployment

This starter is functional, but the following controls are mandatory for a public multi-user service:

- require Amosclaud authentication on every endpoint;
- add `owner_user_id` to projects, variables, runs, and artifacts;
- check project ownership on every read and write;
- execute builds in isolated containers or Server Stations;
- replace `shell=True` with a controlled execution policy;
- apply command allowlists, CPU limits, memory limits, and timeouts;
- clone repositories using short-lived credentials;
- never return secret values to the browser;
- log secret access without logging secret contents;
- use HTTPS and secure cookies;
- scan generated artifacts before publishing;
- use a reverse proxy for live previews;
- require successful DNS verification before attaching a domain.

## Production preview architecture

```text
Amosclaud conversation
        │
        ▼
Task Router / job queue
        │
        ▼
Isolated builder or Server Station
        │
        ├── logs ───────────────► dashboard
        ├── screenshots ────────► artifact storage
        ├── website build ──────► preview service
        └── verification report ► dashboard
                                      │
                                      ▼
                           custom domain router
```

Generated websites should not run inside the main Amosclaud API process. Publish them to a dedicated preview service and return a `preview_url` for the dashboard’s **Open website** button.

## Node.js asynchronous control plane

The first private Node.js/npm orchestration service now lives in `services/control_plane`.

It provides:

- a Fastify task API protected by a private bearer token;
- BullMQ and Redis durable background jobs;
- separate workers with bounded concurrency and cancellation;
- allowlisted, shell-free local command execution for trusted local installations;
- live task logs through Server-Sent Events;
- Chokidar repository watchers with Redis leader election;
- lifecycle coordination with the existing isolated workspace runtime;
- versioned `SKILL.md` distribution through installed npm packages.

See `docs/NODE_NPM_CONTROL_PLANE.md` for architecture and `services/control_plane/README.md` for deployment and API examples.

## Local-first collaboration

Amosclaud supports independent local installations today and a path toward coordinated multi-user cloud services.

- Each installation keeps its own repositories, databases, queues, credentials, models, and execution policies.
- Collaborators can clone the same GitHub repository, work through separate Amosclaud nodes, and exchange changes through branches and pull requests.
- Authenticated organization records, membership roles, and organization repository ownership already provide a multi-user authorization foundation.
- Teams, invitations, shared execution pools, centralized billing, and portal-coordinated deployments remain planned maturity stages.

See `docs/LOCAL_FIRST_MULTI_USER_COLLABORATION.md` for the current trust model, organization roadmap, GitHub collaboration workflow, and future amosclaud.com node-coordination design.

## Amosclaud Copilot

Amosclaud Copilot is the repository-aware coding assistant and multi-agent coordinator for the Amosclaud agent system.

- It understands code and developer instructions with bounded repository context.
- It selects a primary agent and only the supporting agents needed for the task.
- It coordinates Codex, Fixer, Action, Security, Clean, Autonomous, and AI agents.
- It sends authorized execution through the existing governed Autonomous pipeline.
- It exposes profile, agent registry, plan, and run APIs under `/api/v1/copilot`.

See `docs/AMOSCLAUD_COPILOT.md` for the routing model, API contract, editor integration flow, and safety boundaries.
