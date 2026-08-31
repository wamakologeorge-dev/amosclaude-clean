"""Native API router for the Amosclaud Word Book."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from amoscloud_ai.book import AmosclaudBook, BookError

router = APIRouter(prefix="/book", tags=["amosclaud-word-book"])
WEB_DIR = Path(__file__).resolve().parents[3] / "web"


def _book() -> AmosclaudBook:
    return AmosclaudBook()


def _safe(call):
    try:
        return call()
    except BookError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class ChapterCompletion(BaseModel):
    reader: str = Field(min_length=1, max_length=128)


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


@router.get("")
def book_home() -> dict[str, Any]:
    return _safe(lambda: {"manifest": _book().manifest(), "status": _book().status()})


@router.get("/reader", include_in_schema=False)
def book_reader() -> FileResponse:
    return FileResponse(WEB_DIR / "amosclaud-book.html")


@router.get("/status")
def book_status() -> dict[str, Any]:
    return _safe(lambda: _book().status())


@router.get("/chapters")
def book_chapters() -> list[dict[str, Any]]:
    return _safe(lambda: _book().chapters())


@router.get("/chapters/{chapter_id}")
def book_chapter(chapter_id: str) -> dict[str, Any]:
    return _safe(lambda: _book().chapter(chapter_id))


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
