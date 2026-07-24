"""Authenticated Amosclaud control-bus dashboard route."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse

from amoscloud_ai.api.routes.auth import get_user_from_session

router = APIRouter(tags=["amosclaud-control-bus-dashboard"])
WEB_DIR = Path(__file__).resolve().parents[3] / "web"


@router.get("/control-bus", include_in_schema=False)
async def control_bus_dashboard(request: Request):
    """Render live control-bus results for an authenticated Amosclaud user."""
    if not get_user_from_session(request.cookies.get("amos_session")):
        return RedirectResponse("/login", status_code=302)
    return FileResponse(WEB_DIR / "amosclaud-control-bus.html")
