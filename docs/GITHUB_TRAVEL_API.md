# Amosclaud GitHub Travel API

The GitHub Travel API sends the repository agent into an isolated clone, lets it inspect or modify code, runs validation, pushes an agent branch, and returns a pull request to Amosclaud.

## Route

```http
POST /api/v1/agent/github/travel
```

Example:

```json
{
  "repository": "wamakologeorge-dev/amosclaude-clean",
  "objective": "Fix the login session and make Ask mode conversational",
  "base_branch": "main",
  "action": "work-and-open-pr"
}
```

The caller must either:

- be signed in as an Amosclaud administrator, or
- send a valid `X-Amosclaud-Owner-Key` header.

The response includes a task ID, isolated branch, and status URL.

## Status

```http
GET /api/v1/agent/github/travel/{task_id}
```

This returns queued, running, completed, or failed state, logs, the branch name, and the pull request URL when available.

## Allowed actions

- `inspect` — inspect and report; avoid changes unless required
- `work` — work in an isolated branch and validate
- `work-and-open-pr` — complete the full clone/edit/test/push/PR cycle

## Required variables

```env
AMOSCLAUD_OWNER_KEY=<stable-long-random-secret>
AMOSCLAUD_AGENT_REPOSITORY=wamakologeorge-dev/amosclaude-clean
GITHUB_TOKEN=<repository-scoped-token>
ANTHROPIC_API_KEY=<server-side-agent-model-key>
```

Private keys and tokens remain server-side and must never be returned to the browser.

## Safety rules

- the first milestone is restricted to one configured repository
- the agent never pushes directly to `main`
- every task gets an isolated `amosclaud/agent-*` branch
- repository mutation requires administrator or owner approval
- commands are bounded by the existing PR-agent safety policy
- results return through the task status API
