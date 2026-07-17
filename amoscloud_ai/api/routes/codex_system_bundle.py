"""Authenticated API for the canonical Codex system bundle."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from amoscloud_ai.api.routes.auth import get_user_from_session
from amoscloud_ai.api.routes.autonomous_keys import authenticate_autonomous_key
from amoscloud_ai.codex_system_bundle import (
    BUNDLE_NAME,
    BUNDLE_VERSION,
    codex_system_manifest,
    create_codex_system_bundle,
)
from amoscloud_ai.mapping_bundles import MappingBundleStore

router = APIRouter(prefix="/codex/system-bundle", tags=["codex-system-bundle"])
store = MappingBundleStore()


def _bearer(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "").strip()
    scheme, separator, value = authorization.partition(" ")
    if separator and scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return None


def _require_auth(request: Request) -> object:
    user = get_user_from_session(request.cookies.get("amos_session"))
    if user:
        return user
    identity = authenticate_autonomous_key(_bearer(request))
    if identity:
        return identity
    raise HTTPException(status_code=401, detail="Authentication required")


@router.get("/preview")
def preview_codex_system_bundle(request: Request) -> dict:
    """Preview the safe manifest without creating a file."""
    _require_auth(request)
    mappings, metadata = codex_system_manifest()
    return {
        "name": BUNDLE_NAME,
        "version": BUNDLE_VERSION,
        "format": "Amosclaud.bytes",
        "metadata": metadata,
        "mappings": mappings,
    }


@router.post("", status_code=201)
def build_codex_system_bundle(request: Request) -> dict:
    """Create the canonical verified Codex system bundle."""
    _require_auth(request)
    return create_codex_system_bundle(store).as_dict()


@router.get("")
def inspect_codex_system_bundle(request: Request) -> dict:
    """Inspect the latest canonical Codex system bundle."""
    _require_auth(request)
    filename = f"{BUNDLE_NAME}-{BUNDLE_VERSION}.Amosclaud.bytes"
    try:
        return store.read(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Codex system bundle has not been created") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/download")
def download_codex_system_bundle(request: Request) -> FileResponse:
    """Download the verified Codex system bundle."""
    _require_auth(request)
    filename = f"{BUNDLE_NAME}-{BUNDLE_VERSION}.Amosclaud.bytes"
    path = store.root / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Codex system bundle has not been created")
    try:
        store.read(filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FileResponse(
        path,
        filename=filename,
        media_type="application/vnd.amosclaud.bytes",
    )
