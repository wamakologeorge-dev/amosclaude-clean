# SPDX-License-Identifier: LicenseRef-Amosclaud-Book-Proprietary-1.0
"""Native API router for the Amosclaud Word Book, Book Studio, Slapface, and Book licensing."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from amoscloud_ai.book import AmosclaudBook, BookError
from amoscloud_ai.book_license import (
    BOOK_LICENSE_ID,
    BOOK_LICENSE_TERMS_PATH,
    BOOK_LICENSE_VERSION,
    BookLicenseError,
    authorization_status,
    authorize_and_sign,
    issue_grant,
    public_signer,
    verify_receipt,
)
from amoscloud_ai.book_studio import save_chapter, studio_tool_catalog
from amoscloud_ai.book_watchdog import (
    BookWatchdogError,
    RepositoryBookWatchdog,
    secret_verdict,
)
from amoscloud_ai.api.routes.repositories import (
    _access,
    _current_user,
    _db,
    _repo_path,
    _require_write,
)

router = APIRouter(prefix="/book", tags=["amosclaud-word-book"])
REPO_ROOT = Path(__file__).resolve().parents[3]
WEB_DIR = REPO_ROOT / "web"
_LICENSE_UI_TAG = '<script src="/static/amosclaud-book-license.js" defer></script>'


def _book() -> AmosclaudBook:
    return AmosclaudBook()


def _book_html(filename: str) -> HTMLResponse:
    """Serve a Book page with the shared proprietary-license UI boundary."""
    path = WEB_DIR / filename
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Amosclaud Book page is unavailable") from exc
    if _LICENSE_UI_TAG not in source:
        source = source.replace("</body>", f"{_LICENSE_UI_TAG}\n</body>")
    return HTMLResponse(source, headers={"Cache-Control": "no-store"})


def _safe(call):
    try:
        return call()
    except (BookError, BookWatchdogError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _repository_watchdog(repository_id: int, user: sqlite3.Row, *, write: bool = False) -> RepositoryBookWatchdog:
    with _db() as db:
        access = _access(db, repository_id, user["id"])
        if write:
            _require_write(access)
    return RepositoryBookWatchdog(_repo_path(repository_id))


def _actor(user: sqlite3.Row) -> str:
    return f"account:{user['id']}"


def _require_global_book_editor(user: sqlite3.Row) -> None:
    """Keep the public Book readable while limiting canonical platform edits."""
    if not bool(user["is_admin"]):
        raise HTTPException(
            status_code=403,
            detail=(
                "This Book Studio session can read and design drafts, but only an Amosclaud "
                "platform owner/admin can publish the canonical platform Book. Repository owners "
                "publish their own repository Book through repository-scoped controls."
            ),
        )


def _license_subject_exists(db: sqlite3.Connection, subject_type: str, subject_id: int) -> bool:
    table = "users" if subject_type == "account" else "organizations"
    return bool(db.execute(f"SELECT 1 FROM {table} WHERE id=?", (subject_id,)).fetchone())


def _portable_export(book: AmosclaudBook, chapter_id: str | None) -> dict[str, Any]:
    if chapter_id is not None:
        return {
            "book_id": book.manifest().get("book_id"),
            "book_version": book.version(),
            "chapter": book.chapter(chapter_id),
        }
    chapters = [book.chapter(item["id"]) for item in book.chapters() if item["available"]]
    return {
        "book_id": book.manifest().get("book_id"),
        "book_version": book.version(),
        "manifest": book.manifest(),
        "chapters": chapters,
    }


class ChapterCompletion(BaseModel):
    reader: str = Field(min_length=1, max_length=128)


class ChapterStudioSave(BaseModel):
    content: str = Field(min_length=1, max_length=2_000_000)
    summary: str = Field(default="Book Studio chapter update", min_length=1, max_length=500)


class AgentContextRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    chapter_ids: list[str] | None = None


class ChangeReport(BaseModel):
    change_id: str = Field(min_length=1, max_length=200)
    actor: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=4000)
    status: str = "implemented_verification_pending"
    files_changed: list[str]
    chapters_updated: list[str]
    tests: list[Any] = Field(default_factory=list)
    verification: dict[str, Any]
    limitations: list[str] = Field(default_factory=list)
    next_task: str | None = None


class GateRequest(BaseModel):
    changed_files: list[str]
    change_id: str | None = None


class SecretCheckRequest(BaseModel):
    text: str = Field(default="", max_length=2_000_000)


class WatchdogPreflightRequest(BaseModel):
    action: str = Field(min_length=1, max_length=200)
    proposed_text: str = Field(default="", max_length=2_000_000)


class SlapfaceBlockRequest(BaseModel):
    summary: str = Field(min_length=1, max_length=4000)
    chapter_link: str = Field(default=".Amosclaud/book/chapters/00-slapface.md", max_length=500)
    missing_pieces: list[str] = Field(min_length=1, max_length=50)
    reason: str = Field(default="unfinished_work", min_length=1, max_length=100)


class SlapfaceResolveRequest(BaseModel):
    handoff_id: str = Field(min_length=1, max_length=100)
    evidence: list[str] = Field(min_length=1, max_length=50)


class BookLicenseGrantRequest(BaseModel):
    subject_type: Literal["account", "organization"]
    subject_id: int = Field(gt=0)
    permissions: list[Literal["copy", "export", "redistribute"]] = Field(min_length=1, max_length=3)
    repository_id: int | None = Field(default=None, gt=0)
    expires_at: datetime | None = None
    billing_terms_accepted: bool = False


class BookLicenseActionRequest(BaseModel):
    action: Literal["copy", "export", "redistribute"] = "export"
    organization_id: int | None = Field(default=None, gt=0)
    repository_id: int | None = Field(default=None, gt=0)
    chapter_id: str | None = Field(default=None, max_length=20)


class BookReceiptVerifyRequest(BaseModel):
    receipt: dict[str, Any]


@router.get("")
def book_home() -> dict[str, Any]:
    return _safe(lambda: {"manifest": _book().manifest(), "status": _book().status()})


@router.get("/reader", include_in_schema=False)
def book_reader() -> HTMLResponse:
    return _book_html("amosclaud-book.html")


@router.get("/slapface", include_in_schema=False)
def slapface_page() -> HTMLResponse:
    """Open the Word Book with Chapter 00 / Slapface as the first page."""
    return _book_html("amosclaud-book.html")


@router.get("/studio", include_in_schema=False)
def book_studio_page(user: sqlite3.Row = Depends(_current_user)) -> HTMLResponse:
    """Open the authenticated Word-style authoring companion."""
    return _book_html("amosclaud-book-studio.html")


@router.get("/studio/tools")
def book_studio_tools() -> dict[str, Any]:
    """Machine-readable visual-authoring contract for humans and AI agents."""
    return studio_tool_catalog()


@router.get("/license")
def book_license() -> dict[str, Any]:
    manifest = _book().manifest()
    return {
        "license": manifest.get("license_contract"),
        "license_id": BOOK_LICENSE_ID,
        "version": BOOK_LICENSE_VERSION,
        "signer": public_signer(),
        "root_repository_license_unchanged": "MIT",
        "legal_review": "recommended before material commercial enforcement",
    }


@router.get("/license/text", include_in_schema=False)
def book_license_text() -> FileResponse:
    return FileResponse(REPO_ROOT / BOOK_LICENSE_TERMS_PATH, media_type="text/plain")


@router.get("/license/status")
def book_license_status(
    action: Literal["copy", "export", "redistribute"] = Query(default="export"),
    organization_id: int | None = Query(default=None, gt=0),
    repository_id: int | None = Query(default=None, gt=0),
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    with _db() as db:
        try:
            status = authorization_status(
                db,
                account_id=int(user["id"]),
                is_platform_admin=bool(user["is_admin"]),
                action=action,
                organization_id=organization_id,
                repository_id=repository_id,
            )
        except BookLicenseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**status, "license": BOOK_LICENSE_ID, "action": action}


@router.post("/license/grants", status_code=201)
def issue_book_license_grant(
    request: BookLicenseGrantRequest,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    if not bool(user["is_admin"]):
        raise HTTPException(status_code=403, detail="Amosclaud platform owner/admin access is required")
    expires = request.expires_at
    if expires is not None:
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        expires = expires.astimezone(timezone.utc)
    with _db() as db:
        if not _license_subject_exists(db, request.subject_type, request.subject_id):
            raise HTTPException(status_code=404, detail="Book license subject does not exist")
        if request.repository_id is not None and not db.execute(
            "SELECT 1 FROM repositories WHERE id=?", (request.repository_id,)
        ).fetchone():
            raise HTTPException(status_code=404, detail="Repository does not exist")
        try:
            return issue_grant(
                db,
                issued_by_user_id=int(user["id"]),
                subject_type=request.subject_type,
                subject_id=request.subject_id,
                permissions=request.permissions,
                repository_id=request.repository_id,
                expires_at=expires.isoformat() if expires is not None else None,
                billing_terms_accepted=request.billing_terms_accepted,
            )
        except BookLicenseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/license/official-export")
def official_book_export(
    request: BookLicenseActionRequest,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    """Return an authorized Book copy/export with tamper-evident provenance."""
    book = _book()
    try:
        document = _portable_export(book, request.chapter_id)
    except BookError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    with _db() as db:
        try:
            receipt = authorize_and_sign(
                db,
                account_id=int(user["id"]),
                is_platform_admin=bool(user["is_admin"]),
                action=request.action,
                organization_id=request.organization_id,
                repository_id=request.repository_id,
                book_version=book.version(),
                chapter_id=str(request.chapter_id).zfill(2) if request.chapter_id is not None else None,
                content_sha256=digest,
            )
        except BookLicenseError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "amosclaud_book_license_required",
                    "message": str(exc),
                    "license": BOOK_LICENSE_ID,
                    "terms": "/api/v1/book/license/text",
                },
            ) from exc
    return {
        "document": document,
        "provenance": receipt,
        "notice": "Authorized Amosclaud Book copy/export. Preserve this provenance receipt with redistributed authorized material.",
    }


@router.post("/license/verify-receipt")
def verify_book_receipt(request: BookReceiptVerifyRequest) -> dict[str, Any]:
    return verify_receipt(request.receipt)


@router.get("/status")
def book_status() -> dict[str, Any]:
    return _safe(lambda: _book().status())


@router.get("/chapters")
def book_chapters() -> list[dict[str, Any]]:
    return _safe(lambda: _book().chapters())


@router.get("/chapters/{chapter_id}")
def book_chapter(chapter_id: str) -> dict[str, Any]:
    return _safe(lambda: _book().chapter(chapter_id))


@router.put("/chapters/{chapter_id}")
def save_book_chapter(
    chapter_id: str,
    request: ChapterStudioSave,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    _require_global_book_editor(user)
    return _safe(
        lambda: save_chapter(
            _book(),
            chapter_id=chapter_id,
            content=request.content,
            actor=_actor(user),
            summary=request.summary,
        )
    )


@router.post("/chapters/{chapter_id}/complete")
def complete_chapter(chapter_id: str, request: ChapterCompletion) -> dict[str, Any]:
    return _safe(lambda: _book().complete_chapter(chapter_id, request.reader))


@router.get("/products/{product_id}")
def book_product(product_id: str) -> dict[str, Any]:
    return _safe(lambda: _book().product(product_id))


@router.get("/capabilities")
def book_capabilities() -> list[dict[str, Any]]:
    return _safe(lambda: _book().capabilities())


@router.get("/changes")
def book_changes(limit: int = Query(default=100, ge=1, le=1000)) -> list[dict[str, Any]]:
    return _safe(lambda: _book().changes(limit=limit))


@router.post("/changes")
def report_change(report: ChangeReport) -> dict[str, Any]:
    return _safe(lambda: _book().append_change(report.model_dump()))


@router.get("/next-task")
def book_next_task() -> dict[str, Any]:
    return _safe(lambda: _book().next_task())


@router.post("/agent-context")
def book_agent_context(request: AgentContextRequest) -> dict[str, Any]:
    return _safe(lambda: _book().agent_context(request.agent_id, request.chapter_ids))


@router.post("/gate")
def book_gate(request: GateRequest) -> dict[str, Any]:
    return _safe(lambda: _book().gate(request.changed_files, request.change_id))


@router.post("/secret-check")
def book_secret_check(request: SecretCheckRequest) -> dict[str, Any]:
    """Classify likely credentials locally without returning candidate values."""
    return secret_verdict(request.text)


@router.get("/repositories/{repository_id}/watchdog")
def repository_watchdog_status(
    repository_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    watchdog = _repository_watchdog(repository_id, user)
    return _safe(watchdog.status)


@router.post("/repositories/{repository_id}/preflight")
def repository_watchdog_preflight(
    repository_id: int,
    request: WatchdogPreflightRequest,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    watchdog = _repository_watchdog(repository_id, user)
    return _safe(
        lambda: watchdog.preflight(
            actor=_actor(user),
            action=request.action,
            proposed_text=request.proposed_text,
        )
    )


@router.post("/repositories/{repository_id}/slapface/block")
def repository_slapface_block(
    repository_id: int,
    request: SlapfaceBlockRequest,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    watchdog = _repository_watchdog(repository_id, user, write=True)
    return _safe(
        lambda: watchdog.block_handoff(
            actor=_actor(user),
            summary=request.summary,
            chapter_link=request.chapter_link,
            missing_pieces=request.missing_pieces,
            reason=request.reason,
        )
    )


@router.post("/repositories/{repository_id}/slapface/resolve")
def repository_slapface_resolve(
    repository_id: int,
    request: SlapfaceResolveRequest,
    user: sqlite3.Row = Depends(_current_user),
) -> dict[str, Any]:
    watchdog = _repository_watchdog(repository_id, user, write=True)
    return _safe(
        lambda: watchdog.resolve_handoff(
            actor=_actor(user),
            handoff_id=request.handoff_id,
            evidence=request.evidence,
        )
    )
