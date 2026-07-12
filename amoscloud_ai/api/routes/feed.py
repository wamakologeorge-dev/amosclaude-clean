"""Public, sanitized Amosclaud agent-results feed."""

from __future__ import annotations

from fastapi import APIRouter

from amoscloud_ai.api.routes.pipelines import _pipelines

router = APIRouter(prefix="/feed", tags=["public-feed"])


@router.get("", summary="List public Amosclaud agent results")
async def list_public_feed() -> list[dict[str, object]]:
    """Return safe result summaries without exposing source code or private logs."""
    items: list[dict[str, object]] = []
    pipelines = sorted(
        _pipelines.values(),
        key=lambda item: item.started_at,
        reverse=True,
    )

    for pipeline in pipelines[:50]:
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
            }
        )

    return items
