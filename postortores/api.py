"""Standalone HTTP surface for Amosclaud Postortores.

This service can run beside the Amosclaud control plane or on a physical
Amosclaud machine. It uses one bearer token at the service boundary and scopes
all data by the supplied Amosclaud principal. Platform adapters can later map
signed agent/application credentials to the same service contract.
"""

from __future__ import annotations

import hmac
import os
import re
import threading
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import APIRouter, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from .engine import PostortoresEngine
from .service import PostortoresService

router = APIRouter(prefix="/v1", tags=["amosclaud-postortores"])

_KEY_PATTERN = re.compile(r"^[^/]+$")


class StateWrite(BaseModel):
    namespace: str = Field(min_length=1, max_length=200)
    key: str = Field(min_length=1, max_length=500)
    value: dict[str, Any]
    tags: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("key")
    @classmethod
    def _reject_separators(cls, v: str) -> str:
        if not _KEY_PATTERN.match(v):
            raise ValueError("key must not contain '/'")
        return v


class EventWrite(BaseModel):
    stream: str = Field(min_length=1, max_length=300)
    event_type: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any]
    actor: str | None = Field(default=None, max_length=300)


class MemoryWrite(BaseModel):
    content: str = Field(min_length=1, max_length=500_000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding: list[float] | None = Field(default=None, max_length=8192)


class MemorySearch(BaseModel):
    embedding: list[float] = Field(min_length=1, max_length=8192)
    limit: int = Field(default=10, ge=1, le=100)


class EvidenceWrite(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    claim: str = Field(min_length=1, max_length=10_000)
    status: str = Field(pattern="^(?:planned|changed|executed|verified|blocked|failed)$")
    proof: dict[str, Any] = Field(default_factory=dict)


class LinkWrite(BaseModel):
    source: str = Field(min_length=1, max_length=500)
    relation: str = Field(min_length=1, max_length=200)
    target: str = Field(min_length=1, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LeaseRequest(BaseModel):
    resource: str = Field(min_length=1, max_length=500)
    holder: str = Field(min_length=1, max_length=500)
    ttl_seconds: float = Field(default=30.0, gt=0, le=3600)


def _database_path() -> str:
    return os.getenv("AMOSCLAUD_POSTORTORES_PATH", "postortores.db").strip() or "postortores.db"


_engine: PostortoresEngine | None = None
_engine_lock = threading.Lock()


def engine() -> PostortoresEngine:
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is None:
            path = Path(_database_path())
            path.parent.mkdir(parents=True, exist_ok=True)
            _engine = PostortoresEngine(path)
        return _engine


def _principal(
    authorization: str | None,
    amosclaud_principal: str | None,
) -> str:
    expected = os.getenv("AMOSCLAUD_POSTORTORES_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Postortores service token is not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Amosclaud Postortores bearer token required")
    supplied = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid Amosclaud Postortores token")
    principal = (amosclaud_principal or "").strip()
    if not principal:
        raise HTTPException(status_code=400, detail="X-Amosclaud-Principal is required")
    try:
        PostortoresService(engine(), principal)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return principal


def service(
    authorization: str | None = Header(default=None),
    x_amosclaud_principal: str | None = Header(default=None),
) -> PostortoresService:
    principal = _principal(authorization, x_amosclaud_principal)
    return PostortoresService(engine(), principal)


@router.get("/health")
def health() -> dict[str, Any]:
    status = engine().health()
    return {
        "service": status["service"],
        "status": status["status"],
        "storage": status["storage"],
        "native_contract": status["native_contract"],
    }


@router.post("/state", status_code=201)
def put_state(
    body: StateWrite,
    authorization: str | None = Header(default=None),
    x_amosclaud_principal: str | None = Header(default=None),
) -> dict[str, Any]:
    svc = service(authorization, x_amosclaud_principal)
    return svc.record_dict(svc.put_state(body.namespace, body.key, body.value, body.tags))


@router.get("/state/{namespace}/{key}")
def get_state(
    namespace: str,
    key: str,
    version: int | None = Query(default=None, ge=1),
    authorization: str | None = Header(default=None),
    x_amosclaud_principal: str | None = Header(default=None),
) -> dict[str, Any]:
    svc = service(authorization, x_amosclaud_principal)
    record = svc.get_state(namespace, key, version)
    if record is None:
        raise HTTPException(status_code=404, detail="Postortores record not found")
    return svc.record_dict(record)


@router.get("/state/{namespace}/{key}/history")
def state_history(
    namespace: str,
    key: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    authorization: str | None = Header(default=None),
    x_amosclaud_principal: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    svc = service(authorization, x_amosclaud_principal)
    records = svc.state_history(namespace, key)
    return [svc.record_dict(record) for record in records[offset : offset + limit]]


@router.post("/events", status_code=201)
def append_event(
    body: EventWrite,
    authorization: str | None = Header(default=None),
    x_amosclaud_principal: str | None = Header(default=None),
) -> dict[str, int]:
    svc = service(authorization, x_amosclaud_principal)
    return {"id": svc.append_event(body.stream, body.event_type, body.payload, body.actor)}


@router.get("/events/{stream}")
def read_events(
    stream: str,
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    authorization: str | None = Header(default=None),
    x_amosclaud_principal: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    return service(authorization, x_amosclaud_principal).events(stream, after_id, limit)


@router.post("/memory", status_code=201)
def remember(
    body: MemoryWrite,
    authorization: str | None = Header(default=None),
    x_amosclaud_principal: str | None = Header(default=None),
) -> dict[str, int]:
    svc = service(authorization, x_amosclaud_principal)
    return {"id": svc.remember(body.content, body.metadata, body.embedding)}


@router.post("/memory/search")
def search_memory(
    body: MemorySearch,
    authorization: str | None = Header(default=None),
    x_amosclaud_principal: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    return service(authorization, x_amosclaud_principal).search_memory(body.embedding, body.limit)


@router.post("/evidence", status_code=201)
def record_evidence(
    body: EvidenceWrite,
    authorization: str | None = Header(default=None),
    x_amosclaud_principal: str | None = Header(default=None),
) -> dict[str, int]:
    svc = service(authorization, x_amosclaud_principal)
    return {"id": svc.record_evidence(body.subject, body.claim, body.status, body.proof)}


@router.get("/evidence/{subject}")
def evidence(
    subject: str,
    authorization: str | None = Header(default=None),
    x_amosclaud_principal: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    return service(authorization, x_amosclaud_principal).evidence(subject)


@router.post("/graph/link", status_code=201)
def link(
    body: LinkWrite,
    authorization: str | None = Header(default=None),
    x_amosclaud_principal: str | None = Header(default=None),
) -> dict[str, bool]:
    svc = service(authorization, x_amosclaud_principal)
    svc.link(body.source, body.relation, body.target, body.metadata)
    return {"linked": True}


@router.get("/graph/{source}")
def neighbors(
    source: str,
    relation: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
    x_amosclaud_principal: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    return service(authorization, x_amosclaud_principal).neighbors(source, relation)


@router.post("/leases/acquire")
def acquire_lease(
    body: LeaseRequest,
    authorization: str | None = Header(default=None),
    x_amosclaud_principal: str | None = Header(default=None),
) -> dict[str, bool]:
    svc = service(authorization, x_amosclaud_principal)
    return {"acquired": svc.acquire_lease(body.resource, body.holder, body.ttl_seconds)}


app = FastAPI(
    title="Amosclaud Postortores",
    version="0.1.0",
    description="Native Amosclaud data, memory, evidence, event, graph and coordination service.",
)
app.include_router(router)


def main() -> None:
    uvicorn.run(
        "postortores.api:app",
        host=os.getenv("AMOSCLAUD_POSTORTORES_HOST", "127.0.0.1"),
        port=int(os.getenv("AMOSCLAUD_POSTORTORES_PORT", "8765")),
    )


__all__ = ["app", "router", "main"]
