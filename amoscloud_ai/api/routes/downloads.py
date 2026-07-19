"""Stable, allowlisted downloads for Amosclaud server release packages."""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, HTTPException, Request
from fastapi.responses import RedirectResponse

from amoscloud_ai.api.routes import auth
from amoscloud_ai.api.routes.auth import get_user_from_session

router = APIRouter(prefix="/downloads", tags=["downloads"])
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ARTIFACTS = {
    "windows": "Amosclaud-Server.zip",
    "linux": "Amosclaud-Server.tar.gz",
    "macos": "Amosclaud-Server.tar.gz",
    "checksums": "SHA256SUMS.txt",
}


def _repository() -> str:
    repository = os.getenv(
        "AMOSCLAUD_RELEASE_REPOSITORY", "wamakologeorge-dev/amosclaude-clean"
    ).strip()
    if not REPOSITORY_PATTERN.fullmatch(repository):
        raise HTTPException(status_code=503, detail="Release repository is misconfigured")
    return repository


def _asset_url(filename: str) -> str:
    return f"https://github.com/{_repository()}/releases/latest/download/{filename}"


def _db() -> sqlite3.Connection:
    auth.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(auth.DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE IF NOT EXISTS download_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artifact TEXT NOT NULL,
            platform TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)
    db.commit()
    return db


def _record(platform_name: str, artifact: str) -> None:
    with _db() as db:
        db.execute(
            "INSERT INTO download_events(artifact,platform,created_at) VALUES (?,?,?)",
            (artifact, platform_name, datetime.now(timezone.utc).isoformat()),
        )
        db.commit()


@router.get("/latest")
def latest_downloads(request: Request) -> dict:
    base = str(request.base_url).rstrip("/")
    return {
        "product": "Amosclaud Server Workspace",
        "release_channel": "latest",
        "artifacts": {
            platform_name: {
                "filename": filename,
                "download_url": f"{base}/api/v1/downloads/{platform_name}",
            }
            for platform_name, filename in ARTIFACTS.items()
            if platform_name != "checksums"
        },
        "checksums_url": f"{base}/api/v1/downloads/checksums",
        "verification": "Compare the downloaded file against SHA256SUMS.txt before installation.",
    }


@router.get("/{platform_name}")
def download(platform_name: str) -> RedirectResponse:
    filename = ARTIFACTS.get(platform_name.lower())
    if not filename:
        raise HTTPException(status_code=404, detail="Download platform not found")
    _record(platform_name.lower(), filename)
    return RedirectResponse(_asset_url(filename), status_code=307)


@router.get("/metrics/summary")
def download_metrics(amos_session: str | None = Cookie(default=None)) -> dict:
    user = get_user_from_session(amos_session)
    if not user or not bool(user["is_admin"]):
        raise HTTPException(status_code=403, detail="Administrator access required")
    with _db() as db:
        rows = db.execute(
            "SELECT platform,COUNT(*) AS downloads FROM download_events GROUP BY platform"
        ).fetchall()
    return {"downloads": {row["platform"]: row["downloads"] for row in rows}}
