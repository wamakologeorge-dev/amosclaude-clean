"""Native API router for the Amosclaud Word Book and Slapface preflight."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from amoscloud_ai.book import AmosclaudBook, BookError
from amoscloud_ai.slapface import Slapface

router = APIRouter(prefix="/book", tags=["amosclaud-word-book"])
WEB_DIR = Path(__file__).resolve().parents[3] / "web"


def _book() -> AmosclaudBook:
    return AmosclaudBook()


def _slapface() -> Slapface:
    return Slapface()


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
    slapface_scope: str = Field(default="default", min_length=1, max_length=128)


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


class SlapfacePreflightRequest(BaseModel):
    scope: str = Field(default="default", min_length=1, max_length=128)
    agent_id: str = Field(min_length=1, max_length=128)
    objective: str = Field(min_length=1, max_length=8000)
    mode: str = Field(default="plan", min_length=1, max_length=64)
    source: str = Field(default="amosclaud", min_length=1, max_length=128)
    handoff_id: str | None = Field(default=None, max_length=200)


class SlapfaceHandoffRequest(BaseModel):
    scope: str = Field(default="default", min_length=1, max_length=128)
    agent_id: str = Field(min_length=1, max_length=128)
    chapter_id: str = Field(min_length=1, max_length=16)
    next_line: str = Field(min_length=1, max_length=4000)
    risk: str = Field(min_length=1, max_length=4000)
    missing_pieces: list[str] = Field(min_length=1, max_length=100)
    required_paths: list[str] = Field(default_factory=list, max_length=200)
    source: str = Field(default="amosclaud", min_length=1, max_length=128)


class SlapfaceResolveRequest(BaseModel):
    scope: str = Field(default="default", min_length=1, max_length=128)
    handoff_id: str = Field(min_length=1, max_length=200)
    change_id: str = Field(min_length=1, max_length=200)
    actor: str = Field(min_length=1, max_length=128)


class SecretScanRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)
    path: str = Field(default="<submitted-text>", min_length=1, max_length=1000)


@router.get("")
def book_home() -> dict[str, Any]:
    return _safe(
        lambda: {
            "manifest": _book().manifest(),
            "status": _book().status(),
            "slapface": _slapface().status(),
        }
    )


@router.get("/reader", include_in_schema=False)
def book_reader() -> FileResponse:
    return FileResponse(WEB_DIR / "amosclaud-book.html")


@router.get("/slapface", include_in_schema=False)
def slapface_reader() -> FileResponse:
    return FileResponse(WEB_DIR / "amosclaud-slapface.html")


@router.get("/status")
def book_status() -> dict[str, Any]:
    return _safe(lambda: {**_book().status(), "slapface": _slapface().status()})


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
    def build_context() -> dict[str, Any]:
        slapface = _slapface().status(request.slapface_scope)
        if slapface["blocked"]:
            return {
                "agent_id": request.agent_id,
                "slapface": slapface,
                "work_allowed": False,
                "message": (
                    "Slapface must be resolved before a normal Book agent context is issued."
                ),
            }
        return {
            **_book().agent_context(request.agent_id, request.chapter_ids),
            "slapface": slapface,
            "work_allowed": True,
        }

    return _safe(build_context)


@router.post("/gate")
def book_gate(request: GateRequest) -> dict[str, Any]:
    return _safe(lambda: _book().gate(request.changed_files, request.change_id))


@router.get("/slapface/status")
def slapface_status(scope: str = Query(default="default", min_length=1, max_length=128)) -> dict[str, Any]:
    return _safe(lambda: _slapface().status(scope))


@router.post("/slapface/preflight")
def slapface_preflight(request: SlapfacePreflightRequest) -> dict[str, Any]:
    return _safe(
        lambda: _slapface().preflight(
            workspace=None,
            scope=request.scope,
            agent_id=request.agent_id,
            objective=request.objective,
            mode=request.mode,
            source=request.source,
            handoff_id=request.handoff_id,
            scan_secrets=False,
        )
    )


@router.post("/slapface/handoffs")
def slapface_record_handoff(request: SlapfaceHandoffRequest) -> dict[str, Any]:
    return _safe(
        lambda: _slapface().record_handoff(
            scope=request.scope,
            agent_id=request.agent_id,
            chapter_id=request.chapter_id,
            next_line=request.next_line,
            risk=request.risk,
            missing_pieces=request.missing_pieces,
            required_paths=request.required_paths,
            source=request.source,
        )
    )


@router.post("/slapface/resolve")
def slapface_resolve(request: SlapfaceResolveRequest) -> dict[str, Any]:
    return _safe(
        lambda: _slapface().resolve(
            scope=request.scope,
            handoff_id=request.handoff_id,
            change_id=request.change_id,
            actor=request.actor,
        )
    )


@router.post("/slapface/scan")
def slapface_scan(request: SecretScanRequest) -> dict[str, Any]:
    return _safe(lambda: Slapface.scan_text(request.text, path=request.path))
