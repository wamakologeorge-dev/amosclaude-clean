"""Internal client for publishing verified static artifacts to the preview service."""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path
from typing import Any

import requests


MAX_UPLOAD_BYTES = int(
    os.getenv("AMOSCLAUD_PREVIEW_MAX_ARCHIVE_BYTES", "52428800")
)
ALLOWED_SUFFIXES = {
    ".css",
    ".gif",
    ".html",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".map",
    ".mjs",
    ".png",
    ".svg",
    ".txt",
    ".webmanifest",
    ".webp",
    ".woff",
    ".woff2",
    ".xml",
}


class PreviewPublishError(RuntimeError):
    """Raised when a verified static artifact cannot be published safely."""


def _static_archive(root: Path) -> bytes:
    root = root.resolve()
    if not root.is_dir() or not (root / "index.html").is_file():
        raise PreviewPublishError("static preview output must contain index.html")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise PreviewPublishError("static preview output may not contain symlinks")
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if path.suffix.lower() not in ALLOWED_SUFFIXES:
                raise PreviewPublishError(
                    f"static preview file type is not allowed: {path.suffix or '(none)'}"
                )
            archive.write(path, relative.as_posix())
            if buffer.tell() > MAX_UPLOAD_BYTES:
                raise PreviewPublishError("static preview archive exceeds the upload limit")
    data = buffer.getvalue()
    if len(data) > MAX_UPLOAD_BYTES:
        raise PreviewPublishError("static preview archive exceeds the upload limit")
    return data


def publish_static_preview(
    *,
    output_directory: Path,
    owner_user_id: int,
    run_id: str,
) -> dict[str, Any]:
    base_url = os.getenv("AMOSCLAUD_PREVIEW_SERVICE_URL", "").strip().rstrip("/")
    service_key = os.getenv("AMOSCLAUD_PREVIEW_SERVICE_KEY", "").strip()
    if not base_url or not service_key:
        raise PreviewPublishError("preview service is not configured")

    archive = _static_archive(output_directory)
    response = requests.post(
        f"{base_url}/internal/previews",
        headers={"X-Amosclaud-Preview-Key": service_key},
        data={"owner_user_id": str(owner_user_id), "run_id": run_id},
        files={"archive": ("preview.zip", archive, "application/zip")},
        timeout=(5, 60),
    )
    if response.status_code != 201:
        raise PreviewPublishError(
            f"preview service returned HTTP {response.status_code}"
        )
    payload = response.json()
    preview_url = str(payload.get("preview_url") or "")
    preview_id = str(payload.get("preview_id") or "")
    if not preview_url or not preview_id:
        raise PreviewPublishError("preview service returned an invalid response")
    return {
        "preview_id": preview_id,
        "preview_url": base_url + preview_url,
    }
