# Amosclaud Template Studio

Template Studio is a planning service for developers, maintainers, founders and managers who need to create and control open-source project plans, business plans, marketing plans and management plans.

## What it provides

- Word-style browser editor with a ribbon, page canvas, formatting, tables, links and print-to-PDF.
- Open-source, business, marketing, management and blank plan templates.
- Plan status, owner and progress controls.
- Task tracking with priorities, dates and automatic progress calculation.
- Version snapshots and restore support.
- Drawing/paint canvas, shapes, callouts, roadmap and risk-register graphics.
- Policy-driven AI tools for outlines, improvement, summaries, risks, milestones and specialized planning controls.
- JSON and HTML export plus JSON import.
- SQLite persistence and a documented REST API.
- Optional Amosclaud model-station delegation through a governed endpoint.

The local assistant is deterministic and works without any external provider. Set `AMOSCLAUD_TEMPLATE_AI_ENDPOINT` to delegate allowed suggestion actions to an Amosclaud model station. Returned HTML is sanitized and remains **suggest-only**; it is never automatically published.

## Run locally

From the repository root:

```bash
python -m pip install -r services/template_studio/requirements.txt
TEMPLATE_STUDIO_DB=./data/template-studio.db python -m services.template_studio
```

Open `http://localhost:8090`.

## Run with Docker

```bash
docker build -f services/template_studio/Dockerfile -t amosclaud-template-studio .
docker run --rm -p 8090:8090 -v "$PWD/data:/data" amosclaud-template-studio
```

## Environment variables

| Variable | Purpose |
|---|---|
| `PORT` | HTTP port, default `8090` |
| `TEMPLATE_STUDIO_DB` | SQLite database path |
| `AMOSCLAUD_TEMPLATE_AI_ENDPOINT` | Optional governed model-station endpoint |
| `AMOSCLAUD_TEMPLATE_AI_TOKEN` | Optional bearer credential for that endpoint |

## Policy guarantees

- AI actions are allowlisted.
- Plan and instruction sizes are bounded.
- HTML is sanitized before storage and before AI output is returned.
- The assistant cannot automatically publish or execute code.
- External AI is disabled unless an endpoint is explicitly configured.
- Secret values are never returned in the policy result.

## API summary

- `GET /health`
- `GET /api/templates`
- `GET/POST /api/plans`
- `GET/PUT/DELETE /api/plans/{plan_id}`
- `GET/POST /api/plans/{plan_id}/tasks`
- `PATCH/DELETE /api/tasks/{task_id}`
- `GET/POST /api/plans/{plan_id}/versions`
- `POST /api/plans/{plan_id}/versions/{version}/restore`
- `POST /api/plans/{plan_id}/ai`
