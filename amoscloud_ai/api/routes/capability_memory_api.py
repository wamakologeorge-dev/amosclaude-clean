"""Protected API for shared Amosclaud repair knowledge and capability levels."""

from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.capability_memory import (
    capability_profile,
    connect_memory,
    memory_injection,
    record_verified_technique,
    search_verified_techniques,
)

router = APIRouter(prefix="/provider/memory", tags=["amosclaud-capability-memory"])


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=10_000)
    limit: int = Field(default=5, ge=1, le=10)


class VerificationCheck(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    passed: bool


class MemoryEvidence(BaseModel):
    proof_id: str = Field(min_length=4, max_length=200)
    verified: bool
    final_verdict: str = Field(min_length=2, max_length=30)
    checks: list[VerificationCheck] = Field(min_length=1, max_length=50)


class MemoryLearnRequest(BaseModel):
    category: str = Field(min_length=2, max_length=120)
    problem_pattern: str = Field(min_length=5, max_length=1_000)
    root_cause: str = Field(min_length=5, max_length=1_000)
    strategy: list[str] = Field(min_length=1, max_length=20)
    target: str = Field(min_length=1, max_length=500)
    source: str = Field(default="amosclaud", min_length=2, max_length=120)
    confidence: int = Field(default=100, ge=0, le=100)
    combined_fingerprints: list[str] = Field(default_factory=list, max_length=20)
    evidence: MemoryEvidence


def _authorize(authorization: str | None) -> None:
    expected = os.getenv("AMOSCLAUD_MEMORY_ACCESS_KEY", "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Amosclaud capability memory access is not configured",
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
    with connect_memory() as db:
        profile = capability_profile(db)
        techniques = db.execute(
            """SELECT COUNT(*) AS count FROM amosclaud_repair_techniques
               WHERE active=1"""
        ).fetchone()["count"]
    return {
        "status": "ready",
        "storage": "amosclaud-capability-memory",
        "techniques": int(techniques),
        "profile": profile,
    }


@router.post("/search")
def memory_search(
    body: MemorySearchRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _authorize(authorization)
    with connect_memory() as db:
        matches = search_verified_techniques(db, body.query, limit=body.limit)
        profile = capability_profile(db)
    return {
        "matches": matches,
        "injection": memory_injection(matches),
        "profile": profile,
    }


@router.post("/learn")
def memory_learn(
    body: MemoryLearnRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _authorize(authorization)
    evidence = body.evidence.model_dump()
    evidence["checks"] = [item.model_dump() for item in body.evidence.checks]
    try:
        with connect_memory() as db:
            return record_verified_technique(
                db,
                category=body.category,
                problem_pattern=body.problem_pattern,
                root_cause=body.root_cause,
                strategy=body.strategy,
                target=body.target,
                evidence=evidence,
                source=body.source,
                confidence=body.confidence,
                combined_fingerprints=body.combined_fingerprints,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
