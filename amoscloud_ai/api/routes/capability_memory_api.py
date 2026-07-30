"""Protected API for the authoritative Amosclaud Storage repair memory."""

from __future__ import annotations

import hmac
import os
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.repair_knowledge import VerifiedRepairMemory, default_catalog_path

router = APIRouter(prefix="/provider/memory", tags=["amosclaud-capability-memory"])


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=20_000)
    changed_files: list[str] = Field(default_factory=list, max_length=100)
    limit: int = Field(default=4, ge=1, le=10)


class VerificationCheck(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    passed: bool


class MemoryLearnRequest(BaseModel):
    failure_evidence: str = Field(min_length=3, max_length=40_000)
    changed_files: list[str] = Field(min_length=1, max_length=100)
    verified: bool
    final_verdict: str = Field(min_length=2, max_length=30)
    checks: list[VerificationCheck] = Field(min_length=1, max_length=50)
    source: str = Field(default="amosclaud", min_length=2, max_length=200)
    source_run_id: str = Field(default="", max_length=200)


class MemoryFailureRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=2_000)


def _memory() -> VerifiedRepairMemory:
    return VerifiedRepairMemory(default_catalog_path())


def _authorize(authorization: str | None) -> None:
    expected = os.getenv("AMOSCLAUD_MEMORY_ACCESS_KEY", "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Amosclaud Storage memory access is not configured",
        )
    supplied = ""
    if authorization and authorization.startswith("Bearer "):
        supplied = authorization.removeprefix("Bearer ").strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=401,
            detail="A valid Amosclaud memory service key is required",
        )


@router.get("/status")
def memory_status(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _authorize(authorization)
    status = _memory().status()
    return {
        "status": "ready",
        "storage": "amosclaud-storage",
        **status,
    }


@router.post("/search")
def memory_search(
    body: MemorySearchRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _authorize(authorization)
    memory = _memory()
    matches = memory.recall(
        body.query,
        changed_files=body.changed_files,
        limit=body.limit,
    )
    return {
        "matches": [asdict(item) for item in matches],
        "injection": memory.prompt_context(matches),
        "profile": memory.status(),
    }


@router.post("/learn")
def memory_learn(
    body: MemoryLearnRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _authorize(authorization)
    if body.verified is not True:
        raise HTTPException(status_code=400, detail="Memory learning requires verified=true")
    if body.final_verdict.upper() not in {"PASS", "PASSED", "SUCCESS", "SUCCEEDED"}:
        raise HTTPException(
            status_code=400,
            detail="Only a successful final verdict may enter Amosclaud Storage memory",
        )
    if any(item.passed is not True for item in body.checks):
        raise HTTPException(
            status_code=400,
            detail="Every verification check must pass before memory learning",
        )

    verification = [{"name": item.name, "returncode": 0} for item in body.checks]
    try:
        return _memory().learn_verified(
            failure_evidence=body.failure_evidence,
            changed_files=body.changed_files,
            verification_results=verification,
            source=body.source,
            source_run_id=body.source_run_id,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/failed")
def memory_failed(
    body: MemoryFailureRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _authorize(authorization)
    return _memory().record_failure(body.reason)
