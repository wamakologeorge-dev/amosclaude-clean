"""Mapping-bundles API and dashboard routes."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import get_user_from_session
from amoscloud_ai.mapping_bundles import MappingBundleStore

api_router = APIRouter(prefix="/mapping-bundles", tags=["mapping-bundles"])
dashboard_router = APIRouter(tags=["mapping-bundles-dashboard"])
store = MappingBundleStore()
WEB_DIR = Path(__file__).resolve().parents[3] / "web"


class BundleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    version: str = Field(default="1.0.0", min_length=1, max_length=40)
    mappings: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)


def _require_user(request: Request) -> dict:
    user = get_user_from_session(request.cookies.get("amos_session"))
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to manage mapping bundles")
    return dict(user)


@dashboard_router.get("/mapping-bundles", include_in_schema=False)
def mapping_bundles_dashboard(request: Request):
    if not get_user_from_session(request.cookies.get("amos_session")):
        return RedirectResponse("/login", status_code=302)
    return FileResponse(WEB_DIR / "mapping-bundles.html")


@api_router.get("")
def list_bundles(request: Request) -> dict:
    _require_user(request)
    bundles = store.list()
    return {
        "bundles": bundles,
        "summary": {
            "bundle_count": len(bundles),
            "total_bytes": sum(item["byte_size"] for item in bundles),
            "mapping_count": sum(item["mapping_count"] for item in bundles),
            "format": "Amosclaud.bytes",
        },
    }


@api_router.post("", status_code=201)
def create_bundle(body: BundleCreate, request: Request) -> dict:
    user = _require_user(request)
    metadata = dict(body.metadata)
    metadata.setdefault("created_by", user.get("email") or str(user.get("id")))
    try:
        record = store.create(
            name=body.name,
            version=body.version,
            mappings=body.mappings,
            metadata=metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return record.as_dict()


@api_router.get("/{filename}")
def inspect_bundle(filename: str, request: Request) -> dict:
    _require_user(request)
    try:
        return store.read(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Bundle not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@api_router.get("/{filename}/download")
def download_bundle(filename: str, request: Request) -> FileResponse:
    _require_user(request)
    path = store.root / filename
    if not path.is_file() or path.name != filename:
        raise HTTPException(status_code=404, detail="Bundle not found")
    return FileResponse(path, filename=path.name, media_type="application/vnd.amosclaud.bytes")


@api_router.delete("/{filename}", status_code=204)
def delete_bundle(filename: str, request: Request) -> None:
    _require_user(request)
    try:
        store.delete(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Bundle not found") from exc


# Backward-compatible name for code that imports `router`.
router = api_router
