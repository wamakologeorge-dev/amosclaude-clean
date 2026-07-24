"""Public, sanitized Amosclaud agent-results feed."""

from __future__ import annotations

from fastapi import APIRouter

from amoscloud_ai.api.routes.pipelines import list_pipelines

router = APIRouter(prefix="/feed", tags=["public-feed"])


@router.get("", summary="List public Amosclaud agent results")
async def list_public_feed() -> list[dict[str, object]]:
    """Return safe persistent result summaries without exposing private source code."""
    items: list[dict[str, object]] = []
    pipelines = await list_pipelines()

    for pipeline in pipelines[:50]:
        logs: list[str] = []
        for job in pipeline.jobs:
            logs.extend(job.logs[-8:])
        final_text = pipeline.copilot_reply or pipeline.message or "Amosclaud result available."
        items.append(
            {
                "id": pipeline.id,
                "title": "Amosclaud Agent Result",
                "summary": final_text,
                "status": pipeline.status.value,
                "branch": pipeline.branch,
                "started_at": pipeline.started_at,
                "finished_at": pipeline.finished_at,
                "agent": pipeline.copilot_role or "Amosclaud Agent",
                "team": ["Builder", "Tester", "Reviewer"],
                "jobs": [
                    {
                        "id": job.id,
                        "name": job.name,
                        "status": job.status.value,
                        "logs": job.logs[-8:],
                    }
                    for job in pipeline.jobs
                ],
                "recent_logs": logs[-10:],
                "can_request_fix": pipeline.status.value == "failed",
            }
        )

    return items
