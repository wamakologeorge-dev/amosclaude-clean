from __future__ import annotations

import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from app.auth.dependencies import AuthContext, authenticate_websocket_key, require_log_key
from app.redaction.service import redact
from app.redis.client import enqueue_event, get_redis
from app.schemas.logs import AcceptedEvent, BatchAccepted, LogBatch, LogEvent
from app.settings import get_settings

router = APIRouter(prefix="/v1", tags=["logs"])


def _prepare(event: LogEvent, auth: AuthContext) -> dict:
    payload = event.model_dump(mode="json")
    requested_tenant = payload.get("tenant_id")
    if auth.is_admin:
        if not requested_tenant:
            raise HTTPException(422, "tenant_id is required for admin ingestion")
    elif requested_tenant and requested_tenant != auth.tenant_id:
        raise HTTPException(403, "A logging key cannot write to another tenant")
    else:
        payload["tenant_id"] = auth.tenant_id
    return redact(payload)


@router.post("/logs", response_model=AcceptedEvent, status_code=202)
async def ingest_log(
    event: LogEvent, auth: AuthContext = Depends(require_log_key)
) -> AcceptedEvent:
    payload = _prepare(event, auth)
    stream_id = await enqueue_event(payload)
    return AcceptedEvent(event_id=event.event_id, stream_id=stream_id)


@router.post("/logs/batch", response_model=BatchAccepted, status_code=202)
async def ingest_batch(
    batch: LogBatch, auth: AuthContext = Depends(require_log_key)
) -> BatchAccepted:
    settings = get_settings()
    if not batch.events:
        raise HTTPException(422, "At least one event is required")
    if len(batch.events) > settings.max_batch_size:
        raise HTTPException(413, f"Batch limit is {settings.max_batch_size} events")
    accepted = []
    for event in batch.events:
        stream_id = await enqueue_event(_prepare(event, auth))
        accepted.append(AcceptedEvent(event_id=event.event_id, stream_id=stream_id))
    return BatchAccepted(accepted=len(accepted), events=accepted)


@router.websocket("/logs/stream")
async def live_logs(websocket: WebSocket) -> None:
    key = websocket.query_params.get("key", "")
    auth = authenticate_websocket_key(key)
    if auth is None or auth.is_admin:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    settings = get_settings()
    pubsub = get_redis().pubsub()
    channel = f"{settings.redis_live_channel_prefix}:{auth.tenant_id}"
    await pubsub.subscribe(channel)
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("data"):
                payload = message["data"]
                await websocket.send_text(payload if isinstance(payload, str) else json.dumps(payload))
            await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
