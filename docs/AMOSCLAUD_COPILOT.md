# Amosclaud Copilot

Amosclaud Copilot is the repository-aware coding assistant and multi-agent coordinator for Amosclaud.

It is intentionally built on top of the existing governed Autonomous pipeline instead of creating a second unrestricted execution system. Copilot understands a developer request, selects the best primary agent, adds only the supporting agents required for the task, prepares bounded repository context, and hands authorized work to `/api/v1/agent/run`.

## What it does

Amosclaud Copilot can:

- explain repository code and architecture;
- plan and implement features;
- diagnose and repair verified failures;
- prepare and run tests or GitHub Actions work;
- review authentication, permissions, secrets, and dependency risk;
- improve lint, formatting, duplication, and maintainability;
- coordinate full build, deployment, and monitoring work through Amosclaud Autonomous.

It does not bypass branch protection, approval gates, secret controls, verification requirements, or the existing execution policy.

## Agent coordination

Copilot currently coordinates these agents:

| Agent | Primary responsibility |
| --- | --- |
| `amosclaud-codex-agent` | code understanding, implementation, refactoring, and review |
| `amosclaud-fixer` | failure diagnosis and smallest-safe repairs |
| `amosclaud-action` | tests, CI, GitHub Actions, and repository automation |
| `amosclaud-security` | authentication, authorization, secrets, and security review |
| `amosclaud-clean` | lint, formatting, cleanup, and maintainability |
| `amosclaud-autonomous` | end-to-end planning, execution, deployment, monitoring, and evidence |
| `amosclaud-ai-agent` | technical explanation, requirements, and planning |

Routing is deterministic and transparent. A caller can inspect the selected primary agent, supporting agents, execution mode, workflow, context, and exact Autonomous handoff before execution.

## API

### Profile

```http
GET /api/v1/copilot
```

Returns the Copilot identity, mission, directives, agent registry, and endpoint map.

### Agent registry

```http
GET /api/v1/copilot/agents
```

Returns the agents Copilot may coordinate and their public capabilities.

### Plan a task

Authentication is required because editor selections and repository context may be private.

```http
POST /api/v1/copilot/plan
Content-Type: application/json
Cookie: amos_session=...
```

```json
{
  "task": "Fix the failing API test and add a regression check",
  "context": {
    "repository": "wamakologeorge-dev/amosclaude-clean",
    "branch": "feature/copilot-client",
    "file_path": "tests/test_server.py",
    "language": "python",
    "selection": "def test_example(): ...",
    "source": "web-editor"
  }
}
```

The response includes a `handoff` object containing the exact request that would be sent to `/api/v1/agent/run`.

### Run a task

```http
POST /api/v1/copilot/run
Content-Type: application/json
Cookie: amos_session=...
```

The request body is the same as `/plan`. Copilot selects the agents and then starts the existing governed Autonomous workflow. The response contains both the routing plan and the Autonomous execution result, including the pipeline ID.

### Select a specific agent

A caller may request one primary agent explicitly:

```json
{
  "task": "Explain and refactor this function",
  "requested_agent": "codex",
  "context": {
    "branch": "main",
    "file_path": "amoscloud_ai/provider.py"
  }
}
```

Supported aliases include `codex`, `fixer`, `action`, `security`, `clean`, `autonomous`, and `ai`.

## Editor integration contract

A web editor, local extension, or future IDE client should:

1. collect the user instruction;
2. send only the active repository, branch, relative file path, language, and bounded selection needed for the request;
3. call `/api/v1/copilot/plan` when the user wants to preview routing;
4. call `/api/v1/copilot/run` only after the user authorizes execution;
5. poll `/api/v1/pipelines/{pipeline_id}` for durable execution status and evidence;
6. show the selected primary and supporting agents to the user;
7. never send local secrets, `.env` values, credentials, or unrelated files as editor context.

## Safety boundaries

- Repository paths must be relative and cannot contain `..` traversal.
- Editor selections are bounded before they enter pipeline metadata.
- Copilot does not write directly to `main`.
- Sensitive files, merges, deployments, and secret operations remain approval-gated.
- Verification and diff review remain part of the Autonomous workflow.
- Existing pipeline and deployment status strings remain backward compatible for current clients.

## Future extensions

The current release establishes the backend coordination contract. Later clients can add inline completion, chat beside the editor, diff previews, code actions, and pull-request review surfaces without changing the core safety boundary.
