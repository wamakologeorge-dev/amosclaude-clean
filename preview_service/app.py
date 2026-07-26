"""Dedicated static preview service for generated Amosclaud websites.

The service never executes uploaded code. A trusted worker publishes a bounded ZIP
archive with an internal service key. Public users receive static files through an
opaque preview token or a DNS-verified custom domain.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import os
import secrets
import shutil
import sqlite3
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


DATA_ROOT = Path(os.getenv("AMOSCLAUD_PREVIEW_DATA", "data/previews")).resolve()
DB_PATH = DATA_ROOT / "preview.db"
SITES_ROOT = DATA_ROOT / "sites"
MAX_ARCHIVE_BYTES = int(os.getenv("AMOSCLAUD_PREVIEW_MAX_ARCHIVE_BYTES", "52428800"))
MAX_FILES = int(os.getenv("AMOSCLAUD_PREVIEW_MAX_FILES", "2000"))
SERVICE_KEY = os.getenv("AMOSCLAUD_PREVIEW_SERVICE_KEY", "").strip()
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
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'; object-src 'none'; connect-src 'self'; "
        "img-src 'self' data:; font-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}

DATA_ROOT.mkdir(parents=True, exist_ok=True)
SITES_ROOT.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="Amosclaud Preview Service", version="1.0.0")


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS previews (
                id TEXT PRIMARY KEY,
                owner_user_id INTEGER NOT NULL,
                run_id TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                site_path TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_previews_owner
                ON previews(owner_user_id, run_id);

            CREATE TABLE IF NOT EXISTS preview_domains (
                domain TEXT PRIMARY KEY,
                owner_user_id INTEGER NOT NULL,
                preview_id TEXT NOT NULL,
                verification_token TEXT NOT NULL,
                verified INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(preview_id) REFERENCES previews(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_preview_domains_owner
                ON preview_domains(owner_user_id, preview_id);
            """
        )
        db.commit()


init_db()


class DomainRequest(BaseModel):
    owner_user_id: int = Field(gt=0)
    preview_id: str = Field(min_length=1, max_length=100)
    domain: str = Field(min_length=1, max_length=253)


def require_internal_key(request: Request) -> None:
    supplied = request.headers.get("x-amosclaud-preview-key", "")
    if not SERVICE_KEY or not hmac.compare_digest(supplied, SERVICE_KEY):
        raise HTTPException(status_code=401, detail="Invalid preview service key")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _normalize_domain(value: str) -> str:
    domain = value.strip().lower().rstrip(".")
    if not domain or len(domain) > 253:
        raise HTTPException(400, "Enter a valid hostname")
    labels = domain.split(".")
    if len(labels) < 2:
        raise HTTPException(400, "Enter a valid hostname")
    for label in labels:
        if not 1 <= len(label) <= 63:
            raise HTTPException(400, "Enter a valid hostname")
        if label[0] == "-" or label[-1] == "-":
            raise HTTPException(400, "Enter a valid hostname")
        if not all(character.isalnum() or character == "-" for character in label):
            raise HTTPException(400, "Enter a valid hostname")
    return domain


def _safe_member_path(name: str) -> PurePosixPath:
    normalized = PurePosixPath(name)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise HTTPException(400, "Archive contains an unsafe path")
    if not normalized.parts:
        raise HTTPException(400, "Archive contains an empty path")
    return normalized


def _validate_archive(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if not members or len(members) > MAX_FILES:
        raise HTTPException(400, "Preview archive has an invalid file count")

    total_uncompressed = 0
    for member in members:
        path = _safe_member_path(member.filename)
        mode = member.external_attr >> 16
        if mode and (mode & 0o170000) == 0o120000:
            raise HTTPException(400, "Preview archive may not contain symlinks")
        if member.is_dir():
            continue
        total_uncompressed += member.file_size
        if total_uncompressed > MAX_ARCHIVE_BYTES * 4:
            raise HTTPException(400, "Preview archive expands beyond the limit")
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            raise HTTPException(
                400,
                f"Preview file type is not allowed: {path.suffix or '(none)'}",
            )
    return members


def _extract_static_site(data: bytes, destination: Path) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise HTTPException(400, "Preview upload must be a valid ZIP archive") from exc

    members = _validate_archive(archive)
    destination.mkdir(parents=True, exist_ok=False)
    try:
        for member in members:
            relative = _safe_member_path(member.filename)
            target = destination.joinpath(*relative.parts).resolve()
            try:
                target.relative_to(destination.resolve())
            except ValueError as exc:
                raise HTTPException(400, "Archive path escapes the preview root") from exc
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
        if not (destination / "index.html").is_file():
            raise HTTPException(400, "Preview archive must contain index.html")
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    finally:
        archive.close()


def _site_file(site_path: str, asset_path: str) -> Path:
    root = Path(site_path).resolve()
    requested = asset_path.strip("/") or "index.html"
    candidate = root.joinpath(*PurePosixPath(requested).parts).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(404, "Preview asset not found") from exc
    if candidate.is_dir():
        candidate = candidate / "index.html"
    if not candidate.is_file():
        raise HTTPException(404, "Preview asset not found")
    return candidate


def _preview_by_token(token: str) -> sqlite3.Row | None:
    with connect() as db:
        return db.execute(
            "SELECT * FROM previews WHERE token_hash=?",
            (_token_hash(token),),
        ).fetchone()


def _preview_by_domain(domain: str) -> sqlite3.Row | None:
    with connect() as db:
        return db.execute(
            """
            SELECT previews.* FROM preview_domains
            JOIN previews ON previews.id=preview_domains.preview_id
            WHERE preview_domains.domain=? AND preview_domains.verified=1
            """,
            (domain,),
        ).fetchone()


def _static_response(path: Path) -> FileResponse:
    return FileResponse(path, headers=SECURITY_HEADERS)


@app.post("/internal/previews", status_code=201)
async def publish_preview(
    owner_user_id: Annotated[int, Form(gt=0)],
    run_id: Annotated[str, Form(min_length=1, max_length=100)],
    archive: Annotated[UploadFile, File()],
    _: None = Depends(require_internal_key),
) -> dict[str, str]:
    data = await archive.read(MAX_ARCHIVE_BYTES + 1)
    if len(data) > MAX_ARCHIVE_BYTES:
        raise HTTPException(413, "Preview archive is too large")

    preview_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)
    destination = SITES_ROOT / preview_id
    _extract_static_site(data, destination)

    with connect() as db:
        db.execute(
            """
            INSERT INTO previews(
                id, owner_user_id, run_id, token_hash, site_path, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                preview_id,
                owner_user_id,
                run_id,
                _token_hash(token),
                str(destination),
                int(time.time()),
            ),
        )
        db.commit()
    return {
        "preview_id": preview_id,
        "preview_url": f"/p/{token}/",
    }


@app.get("/p/{token}/{asset_path:path}")
async def serve_token_preview(token: str, asset_path: str) -> FileResponse:
    preview = _preview_by_token(token)
    if not preview:
        raise HTTPException(404, "Preview not found")
    return _static_response(_site_file(str(preview["site_path"]), asset_path))


@app.post("/internal/domains")
async def attach_domain(
    payload: DomainRequest,
    _: None = Depends(require_internal_key),
) -> dict[str, object]:
    domain = _normalize_domain(payload.domain)

    with connect() as db:
        preview = db.execute(
            "SELECT id FROM previews WHERE id=? AND owner_user_id=?",
            (payload.preview_id, payload.owner_user_id),
        ).fetchone()
        if not preview:
            raise HTTPException(404, "Preview not found")

        existing = db.execute(
            """
            SELECT owner_user_id, verification_token, verified
            FROM preview_domains WHERE domain=?
            """,
            (domain,),
        ).fetchone()
        if existing and int(existing["owner_user_id"]) != payload.owner_user_id:
            raise HTTPException(409, "Domain is already attached to another owner")

        now = int(time.time())
        if existing and bool(existing["verified"]):
            token = str(existing["verification_token"])
            verified = True
            db.execute(
                """
                UPDATE preview_domains
                SET preview_id=?, created_at=?
                WHERE domain=? AND owner_user_id=?
                """,
                (payload.preview_id, now, domain, payload.owner_user_id),
            )
        else:
            token = "amosclaud-preview=" + secrets.token_urlsafe(24)
            verified = False
            if existing:
                db.execute(
                    """
                    UPDATE preview_domains
                    SET preview_id=?, verification_token=?, verified=0, created_at=?
                    WHERE domain=? AND owner_user_id=?
                    """,
                    (
                        payload.preview_id,
                        token,
                        now,
                        domain,
                        payload.owner_user_id,
                    ),
                )
            else:
                db.execute(
                    """
                    INSERT INTO preview_domains(
                        domain, owner_user_id, preview_id,
                        verification_token, verified, created_at
                    ) VALUES (?, ?, ?, ?, 0, ?)
                    """,
                    (
                        domain,
                        payload.owner_user_id,
                        payload.preview_id,
                        token,
                        now,
                    ),
                )
        db.commit()
    return {
        "domain": domain,
        "verified": verified,
        "dns_record": {
            "type": "TXT",
            "name": f"_amosclaud-preview.{domain}",
            "value": token,
        },
    }


@app.post("/internal/domains/verify")
async def verify_domain(
    payload: DomainRequest,
    _: None = Depends(require_internal_key),
) -> dict[str, object]:
    domain = _normalize_domain(payload.domain)
    with connect() as db:
        record = db.execute(
            """
            SELECT verification_token FROM preview_domains
            WHERE domain=? AND preview_id=? AND owner_user_id=?
            """,
            (domain, payload.preview_id, payload.owner_user_id),
        ).fetchone()
    if not record:
        raise HTTPException(404, "Domain attachment not found")

    try:
        import dns.resolver

        answers = dns.resolver.resolve(
            f"_amosclaud-preview.{domain}",
            "TXT",
            lifetime=8,
        )
        values = {b"".join(answer.strings).decode() for answer in answers}
    except Exception:
        values = set()

    verified = record["verification_token"] in values
    if verified:
        with connect() as db:
            db.execute(
                """
                UPDATE preview_domains SET verified=1
                WHERE domain=? AND preview_id=? AND owner_user_id=?
                """,
                (domain, payload.preview_id, payload.owner_user_id),
            )
            db.commit()
    return {"domain": domain, "verified": verified}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ready", "mode": "static-only"}


@app.get("/{asset_path:path}", include_in_schema=False)
async def serve_verified_domain(request: Request, asset_path: str) -> FileResponse:
    host = request.headers.get("host", "").split(":", 1)[0].lower().rstrip(".")
    preview = _preview_by_domain(host)
    if not preview:
        raise HTTPException(404, "Verified preview domain not found")
    return _static_response(_site_file(str(preview["site_path"]), asset_path))
