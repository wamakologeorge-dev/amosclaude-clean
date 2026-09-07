"""Authenticated online synchronization routes for local-first Amosclaud Book clients."""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.repositories import _current_user, _db
from amoscloud_ai.book_sync import apply_operation, list_documents

router = APIRouter(prefix="/book", tags=["amosclaud-book-sync"])


class OfflineSyncRequest(BaseModel):
    operationId: str = Field(min_length=1, max_length=200)
    documentId: str = Field(min_length=1, max_length=200)
    operation: str = Field(min_length=1, max_length=32)
    baseServerRevision: int | None = Field(default=None, ge=0)
    payload: dict[str, Any] | None = None


@router.post("/offline-sync")
def offline_sync(request: OfflineSyncRequest, user: sqlite3.Row = Depends(_current_user)) -> dict[str, Any]:
    try:
        with _db() as db:
            result = apply_operation(
                db,
                user_id=int(user["id"]),
                operation_id=request.operationId,
                document_id=request.documentId,
                operation=request.operation,
                payload=request.payload,
                base_server_revision=request.baseServerRevision,
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result.get("status") == "conflict":
        raise HTTPException(status_code=409, detail=result)
    return result


@router.get("/offline-sync")
def offline_sync_documents(user: sqlite3.Row = Depends(_current_user)) -> dict[str, Any]:
    with _db() as db:
        return {"documents": list_documents(db, user_id=int(user["id"]))}
