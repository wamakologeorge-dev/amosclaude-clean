"""Persistent Amosclaud bundle registry and download host."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

router = APIRouter(prefix="/bundles", tags=["bundle-host"])

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_PLATFORM_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")
_ALLOWED_SUFFIXES = (".zip", ".tar.gz", ".tgz", ".tar.zst")


def bundle_root() -> Path:
    root = Path(os.getenv("AMOSCLAUD_BUNDLE_ROOT", "data/bundles")).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _max_bundle_bytes() -> int:
    configured = int(os.getenv("AMOSCLAUD_BUNDLE_MAX_BYTES", str(2 * 1024**3)))
    return max(1024, min(configured, 20 * 1024**3))


def _expected_keys() -> tuple[str, ...]:
    names = ("AMOSCLAUD_BUNDLES_API_KEY", "AMOSCLAUD_API_KEY", "EXTERNAL_API_KEY")
    return tuple(value for name in names if (value := os.getenv(name, "").strip()))


def _authorize(authorization: str | None, x_api_key: str | None) -> None:
    expected = _expected_keys()
    if not expected:
        raise HTTPException(status_code=503, detail="Bundle host API key is not configured")
    bearer = authorization.removeprefix("Bearer ").strip() if authorization else ""
    supplied = tuple(value for value in (bearer, (x_api_key or "").strip()) if value)
    if not any(
        secrets.compare_digest(candidate, accepted)
        for candidate in supplied
        for accepted in expected
    ):
        raise HTTPException(status_code=401, detail="Invalid Amosclaud API key")


def _metadata_path(bundle_id: str) -> Path:
    if not _ID_PATTERN.fullmatch(bundle_id):
        raise HTTPException(status_code=404, detail="Bundle not found")
    return bundle_root() / bundle_id / "metadata.json"


def _load(bundle_id: str) -> dict[str, Any]:
    path = _metadata_path(bundle_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Bundle not found")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Bundle metadata is unreadable") from exc
    if not isinstance(payload, dict) or payload.get("bundle_id") != bundle_id:
        raise HTTPException(status_code=500, detail="Bundle metadata is invalid")
    return payload


def _public_metadata(metadata: dict[str, Any], request: Request) -> dict[str, Any]:
    result = dict(metadata)
    bundle_id = str(result["bundle_id"])
    result["download_url"] = (
        f"{str(request.base_url).rstrip('/')}/api/v1/bundles/{bundle_id}/download"
    )
    return result


@router.get("/health")
def health() -> dict[str, Any]:
    root = bundle_root()
    return {
        "status": "ok",
        "service": "amosclaud-bundles-api-host",
        "storage": "available" if root.is_dir() else "unavailable",
        "authentication_required": True,
    }


@router.get("")
def list_bundles(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> dict[str, Any]:
    _authorize(authorization, x_api_key)
    records = []
    for path in sorted(bundle_root().glob("*/metadata.json")):
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
            identifier = str(metadata.get("bundle_id", "")) if isinstance(metadata, dict) else ""
            if isinstance(metadata, dict) and _ID_PATTERN.fullmatch(identifier):
                records.append(_public_metadata(metadata, request))
        except (OSError, json.JSONDecodeError):
            continue
    records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return {"object": "list", "data": records, "count": len(records)}


@router.post("", status_code=201)
async def upload_bundle(
    request: Request,
    file: Annotated[UploadFile, File(description="Versioned Amosclaud bundle archive")],
    version: Annotated[str, Form()],
    platform: Annotated[str, Form()],
    channel: Annotated[str, Form()] = "stable",
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> dict[str, Any]:
    _authorize(authorization, x_api_key)
    version = version.strip()
    platform = platform.strip().lower()
    channel = channel.strip().lower()
    filename = Path(file.filename or "").name
    if not _VERSION_PATTERN.fullmatch(version):
        raise HTTPException(status_code=422, detail="Invalid bundle version")
    if not _PLATFORM_PATTERN.fullmatch(platform) or not _PLATFORM_PATTERN.fullmatch(channel):
        raise HTTPException(status_code=422, detail="Invalid bundle platform or channel")
    if filename != (file.filename or "") or not filename.endswith(_ALLOWED_SUFFIXES):
        raise HTTPException(status_code=422, detail="Unsupported or unsafe bundle filename")

    bundle_id = f"amosclaud-{version.lower()}-{platform}-{channel}"
    if not _ID_PATTERN.fullmatch(bundle_id):
        raise HTTPException(status_code=422, detail="Generated bundle identifier is invalid")
    destination_dir = bundle_root() / bundle_id
    if destination_dir.exists():
        raise HTTPException(status_code=409, detail="Bundle version already exists")

    destination_dir.mkdir(parents=False)
    digest = hashlib.sha256()
    size = 0
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination_dir, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > _max_bundle_bytes():
                    raise HTTPException(
                        status_code=413,
                        detail="Bundle exceeds configured size limit",
                    )
                digest.update(chunk)
                temporary.write(chunk)
        archive_path = destination_dir / filename
        temporary_path.replace(archive_path)
        metadata = {
            "schema_version": "1.0.0",
            "bundle_id": bundle_id,
            "product": "Amosclaud",
            "version": version,
            "platform": platform,
            "channel": channel,
            "filename": filename,
            "content_type": file.content_type or "application/octet-stream",
            "size_bytes": size,
            "sha256": digest.hexdigest(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "artifact_id": str(uuid.uuid4()),
        }
        metadata_path = destination_dir / "metadata.json"
        pending = destination_dir / ".metadata.json.tmp"
        pending.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        pending.replace(metadata_path)
        return _public_metadata(metadata, request)
    except Exception:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
        if destination_dir.exists() and not any(destination_dir.iterdir()):
            destination_dir.rmdir()
        raise
    finally:
        await file.close()


@router.get("/{bundle_id}")
def get_bundle(
    bundle_id: str,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> dict[str, Any]:
    _authorize(authorization, x_api_key)
    return _public_metadata(_load(bundle_id), request)


@router.get("/{bundle_id}/download")
def download_bundle(
    bundle_id: str,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> FileResponse:
    _authorize(authorization, x_api_key)
    metadata = _load(bundle_id)
    archive = _metadata_path(bundle_id).parent / Path(str(metadata["filename"])).name
    if not archive.is_file():
        raise HTTPException(status_code=404, detail="Bundle archive not found")
    return FileResponse(
        archive,
        filename=str(metadata["filename"]),
        media_type=str(metadata["content_type"]),
        headers={
            "ETag": f'"sha256:{metadata["sha256"]}"',
            "X-Amosclaud-SHA256": str(metadata["sha256"]),
        },
    )
