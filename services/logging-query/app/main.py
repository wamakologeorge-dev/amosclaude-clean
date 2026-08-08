from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime

import asyncpg
from fastapi import Depends, FastAPI, HTTPException, Query

from app.filters import build_log_query
from app.pagination import encode_cursor
from app.permissions import QueryIdentity, require_query_identity

DATABASE_URL = os.getenv("AMOSCLAUD_LOGGING_DATABASE_URL", "postgresql://amosclaud:amosclaud@postgres:5432/amosclaud_logs")
pool: asyncpg.Pool | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    yield
    await pool.close()


app = FastAPI(title="Amosclaud Logging Query", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    if pool is None:
        return {"status": "not-ready"}
    await pool.fetchval("SELECT 1")
    return {"status": "ready"}


@app.get("/v1/logs")
async def list_logs(
    tenant_id: str | None = None,
    level: str | None = None,
    service: str | None = None,
    environment: str | None = None,
    trace_id: str | None = None,
    request_id: str | None = None,
    search: str | None = None,
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    identity: QueryIdentity = Depends(require_query_identity),
):
    target_tenant = tenant_id if identity.is_admin else identity.tenant_id
    if identity.is_admin and not target_tenant:
        raise HTTPException(422, "tenant_id is required for admin queries")
    if not identity.is_admin and tenant_id and tenant_id != identity.tenant_id:
        raise HTTPException(403, "A logging key cannot query another tenant")
    sql, values = build_log_query(
        target_tenant, level=level, service=service, environment=environment,
        trace_id=trace_id, request_id=request_id, search=search,
        from_time=from_time, to_time=to_time, cursor=cursor, limit=limit,
    )
    assert pool is not None
    rows = [dict(row) for row in await pool.fetch(sql, *values)]
    next_cursor = None
    if len(rows) == limit:
        last = rows[-1]
        next_cursor = encode_cursor(last["timestamp"], str(last["event_id"]))
    return {"items": rows, "next_cursor": next_cursor}
