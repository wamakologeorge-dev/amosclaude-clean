"""Authenticated browser page for Amosclaud Bundles."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse

from amoscloud_ai.api.routes.auth import get_user_from_session

router = APIRouter(tags=["bundle-pages"])
WEB_ROOT = Path(__file__).resolve().parents[3] / "web"


@router.get("/bundles", include_in_schema=False)
async def bundles_page(request: Request):
    if not get_user_from_session(request.cookies.get("amos_session")):
        return RedirectResponse("/login", status_code=302)
    return FileResponse(WEB_ROOT / "bundles.html")
