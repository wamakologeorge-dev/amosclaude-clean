"""Authenticated API for building and downloading Amosclaud bundles."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import get_user_from_session
from amoscloud_ai.bundles import BundleError, build_bundle, read_manifests

router = APIRouter(prefix="/bundles", tags=["bundles"])
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BUNDLE_ROOT = WORKSPACE_ROOT / "data" / "bundles"
BUNDLE_TYPES = {
    "source": "Portable source package for development and review.",
    "runtime": "Application runtime source and configuration without secrets.",
    "connector": "Connector package for Codex, MCP, or another integration.",
    "deployment": "Deployment-ready source package with a declared entrypoint.",
    "extension": "Reusable Amosclaud extension or plugin package.",
}
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


class BundleBuildRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    version: str = Field(default="0.1.0", min_length=1, max_length=40)
    bundle_type: Literal["source", "runtime", "connector", "deployment", "extension"] = "source"
    source_path: str | None = Field(default=None, max_length=500)
    description: str = Field(default="", max_length=1000)
    entrypoint: str | None = Field(default=None, max_length=300)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _user(request: Request):
    user = get_user_from_session(request.cookies.get("amos_session"))
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to use Amosclaud Bundles")
    return user


def _validate_identifier(label: str, value: str) -> str:
    cleaned = value.strip()
    if not IDENTIFIER.fullmatch(cleaned):
        raise HTTPException(status_code=422, detail=f"{label} contains unsupported characters")
    return cleaned


@router.get("", summary="List the current user's bundles")
def list_bundles(request: Request) -> dict:
    user = _user(request)
    return {
        "format": "amosclaud.bundle.v1",
        "bundle_types": BUNDLE_TYPES,
        "bundles": list(read_manifests(BUNDLE_ROOT, int(user["id"]))),
    }


@router.get("/types", summary="List supported Amosclaud bundle types")
def list_bundle_types(request: Request) -> dict:
    _user(request)
    return {"format": "amosclaud.bundle.v1", "types": BUNDLE_TYPES}


@router.post("", status_code=201, summary="Build an Amosclaud bundle")
def create_bundle(body: BundleBuildRequest, request: Request) -> dict:
    user = _user(request)
    name = _validate_identifier("Bundle name", body.name)
    version = _validate_identifier("Bundle version", body.version)
    if body.bundle_type == "deployment" and not body.entrypoint:
        raise HTTPException(status_code=422, detail="Deployment bundles require an entrypoint")
    try:
        artifact = build_bundle(
            workspace_root=WORKSPACE_ROOT,
            output_root=BUNDLE_ROOT,
            user_id=int(user["id"]),
            name=name,
            version=version,
            bundle_type=body.bundle_type,
            source_path=body.source_path,
            description=body.description,
            entrypoint=body.entrypoint,
            metadata={
                **body.metadata,
                "owner_name": user["name"],
                "owner_email": user["email"],
            },
        )
    except BundleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    manifest = artifact.manifest.to_dict()
    return {
        "created": True,
        "bundle": manifest,
        "archive_size": artifact.archive_size,
        "download_url": f"/api/v1/bundles/{artifact.manifest.bundle_id}/download",
    }


@router.get("/{bundle_id}", summary="Read an Amosclaud bundle manifest")
def get_bundle(bundle_id: str, request: Request) -> dict:
    user = _user(request)
    bundle_id = _validate_identifier("Bundle ID", bundle_id)
    manifests = read_manifests(BUNDLE_ROOT, int(user["id"]))
    manifest = next((item for item in manifests if item.get("bundle_id") == bundle_id), None)
    if not manifest:
        raise HTTPException(status_code=404, detail="Bundle not found")
    return {"bundle": manifest, "download_url": f"/api/v1/bundles/{bundle_id}/download"}


@router.get("/{bundle_id}/download", summary="Download an Amosclaud bundle")
def download_bundle(bundle_id: str, request: Request):
    user = _user(request)
    bundle_id = _validate_identifier("Bundle ID", bundle_id)
    archive = BUNDLE_ROOT / str(user["id"]) / f"{bundle_id}.amosbundle"
    manifest_path = archive.with_suffix(".json")
    if not archive.is_file() or not manifest_path.is_file():
        raise HTTPException(status_code=404, detail="Bundle not found")
    return FileResponse(
        archive,
        media_type="application/vnd.amosclaud.bundle+zip",
        filename=archive.name,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
