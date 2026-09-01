"""Native API router for the Amosclaud Word Book, Book Studio, and Slapface."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from amoscloud_ai.book import AmosclaudBook, BookError
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
WEB_DIR = Path(__file__).resolve().parents[3] / "web"


def _book() -> AmosclaudBook:
    return AmosclaudBook()


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


@router.get("")
def book_home() -> dict[str, Any]:
    return _safe(lambda: {"manifest": _book().manifest(), "status": _book().status()})


@router.get("/reader", include_in_schema=False)
def book_reader() -> FileResponse:
    return FileResponse(WEB_DIR / "amosclaud-book.html")


@router.get("/slapface", include_in_schema=False)
def slapface_page() -> FileResponse:
    """Open the Word Book with Chapter 00 / Slapface as the first page."""
    return FileResponse(WEB_DIR / "amosclaud-book.html")


@router.get("/studio", include_in_schema=False)
def book_studio_page(user: sqlite3.Row = Depends(_current_user)) -> FileResponse:
    """Open the authenticated Word-style authoring companion."""
    return FileResponse(WEB_DIR / "amosclaud-book-studio.html")


@router.get("/studio/tools")
def book_studio_tools() -> dict[str, Any]:
    """Machine-readable visual-authoring contract for humans and AI agents."""
    return studio_tool_catalog()


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
