"""Authenticated control-bus dashboard and modular extension host."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse

from amoscloud_ai.api.routes.auth import get_user_from_session
from amoscloud_ai.extensions.runtime import bootstrap_registry

router = APIRouter(tags=["amosclaud-control-bus-dashboard"])
WEB_DIR = Path(__file__).resolve().parents[3] / "web"


@router.get("/control-bus", include_in_schema=False)
async def control_bus_dashboard(request: Request):
    """Render live control-bus results for an authenticated Amosclaud user."""
    if not get_user_from_session(request.cookies.get("amos_session")):
        return RedirectResponse("/login", status_code=302)
    return FileResponse(WEB_DIR / "amosclaud-control-bus.html")


@router.get("/admin/extensions", include_in_schema=False)
async def extension_control_panel(request: Request):
    """Render the administrator plugin, MCP, and feature-flag control panel."""
    user = get_user_from_session(request.cookies.get("amos_session"))
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not bool(user["is_admin"]):
        return RedirectResponse("/cloud/agent", status_code=302)
    return FileResponse(WEB_DIR / "extensions.html")


# The main application already includes this router. It therefore becomes the
# stable extension host: drop-in modules and Python entry points can add routes
# without another edit to the FastAPI core.
plugin_registry = bootstrap_registry(router)
