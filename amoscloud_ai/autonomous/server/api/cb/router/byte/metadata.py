"""Autonomous byte metadata API for verified ``Amosclaud.bytes`` bundles."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from amoscloud_ai.api.routes.auth import get_user_from_session
from amoscloud_ai.api.routes.autonomous_keys import authenticate_autonomous_key
from amoscloud_ai.mapping_bundles import MappingBundleStore

router = APIRouter(
    prefix="/autonomous/server/api/cb/router/byte/metadata",
    tags=["autonomous-byte-metadata"],
)
store = MappingBundleStore()


def _bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "").strip()
    scheme, separator, value = authorization.partition(" ")
    if separator and scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return None


def _require_identity(request: Request) -> Any:
    user = get_user_from_session(request.cookies.get("amos_session"))
    if user:
        return user
    identity = authenticate_autonomous_key(_bearer_token(request))
    if not identity:
        raise HTTPException(
            status_code=401,
            detail="A signed-in session or valid Amosclaud autonomous key is required",
        )
    return identity


def _metadata_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "filename": item.get("filename"),
        "name": item.get("name"),
        "version": item.get("version"),
        "byte_size": item.get("byte_size", 0),
        "mapping_count": item.get("mapping_count", 0),
        "created_at": item.get("created_at"),
        "format": "Amosclaud.bytes",
        "media_type": "application/vnd.amosclaud.bytes",
        "verified": True,
    }


@router.get("")
def byte_metadata_index(request: Request) -> dict[str, Any]:
    """Return verified byte-bundle metadata without exposing bundle payloads."""
    _require_identity(request)
    bundles = [_metadata_record(item) for item in store.list()]
    return {
        "name": "autonomous.server.api.cb.router.byte.metadata",
        "contract": "amosclaud.autonomous.byte-metadata/v1",
        "format": "Amosclaud.bytes",
        "bundle_count": len(bundles),
        "total_bytes": sum(int(item["byte_size"]) for item in bundles),
        "bundles": bundles,
    }


@router.get("/{filename}")
def byte_metadata_detail(filename: str, request: Request) -> dict[str, Any]:
    """Verify one bundle and return its decoded metadata and integrity facts."""
    _require_identity(request)
    try:
        manifest = store.read(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Byte bundle not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    path = store.root / filename
    if path.name != filename or not path.is_file():
        raise HTTPException(status_code=404, detail="Byte bundle not found")

    return {
        "name": "autonomous.server.api.cb.router.byte.metadata",
        "contract": "amosclaud.autonomous.byte-metadata/v1",
        "filename": filename,
        "byte_size": path.stat().st_size,
        "format": "Amosclaud.bytes",
        "media_type": "application/vnd.amosclaud.bytes",
        "verified": True,
        "schema": manifest.get("schema"),
        "bundle": {
            "name": manifest.get("name"),
            "version": manifest.get("version"),
            "created_at": manifest.get("created_at"),
            "mapping_count": len(manifest.get("mappings") or {}),
            "metadata": manifest.get("metadata") or {},
        },
    }
