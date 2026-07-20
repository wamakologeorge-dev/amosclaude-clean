"""Compatibility entry point for the unified Amosclaud Autonomous platform.

This module intentionally reuses the canonical application. It must not create
another FastAPI app or a second Autonomous/Fixer runtime.
"""

from __future__ import annotations

from fastapi.responses import HTMLResponse

from amoscloud_ai.main import create_app
from .router import router
from .operations_router import router as operations_router

app = create_app()

# Preserve the historical v2 endpoints without creating another application.
app.include_router(router)
app.include_router(operations_router)


if not any(getattr(route, "path", "") == "/agent-mission-control" for route in app.routes):

    @app.get("/agent-mission-control", response_class=HTMLResponse, include_in_schema=False)
    def agent_mission_control() -> str:
        return (
            "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Amosclaud Autonomous Mission Control</title></head><body>"
            "<main><h1>Amosclaud Autonomous Mission Control</h1>"
            "<p>This compatibility surface is connected to the canonical "
            "Amosclaud platform, Agent, Fixer, repository, and pipeline APIs.</p>"
            "<p><a href='/autonomous'>Open Amosclaud Autonomous</a></p>"
            "</main></body></html>"
        )


__all__ = ["app", "create_app"]
