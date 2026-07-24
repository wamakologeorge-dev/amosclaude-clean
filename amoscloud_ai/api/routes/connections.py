"""Connection readiness API for the Amosclaud Autonomous platform."""

from __future__ import annotations

from fastapi import APIRouter

from amoscloud_ai.agent.preflight import run_preflight

router = APIRouter(prefix="/connections", tags=["connections"])


@router.get("/preflight")
def connections_preflight() -> dict:
    """Report whether the local Autonomous runtime can accept work.

    This endpoint intentionally does not require an OpenAI credential. Amosclaud
    may use its own model gateway or operate in inspection-only mode, so model
    provider credentials are reported separately from core platform readiness.
    """

    report = run_preflight(require_openai=False)
    return {
        "status": "ready" if report.ready else "degraded",
        "ready": report.ready,
        "service": "amosclaud-connections",
        "checks": report.checks,
        "errors": report.errors,
        "details": report.details,
    }
