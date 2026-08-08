from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from redis.asyncio import Redis

from app.settings import get_settings


@lru_cache
def get_redis() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


async def enqueue_event(event: dict[str, Any]) -> str:
    settings = get_settings()
    client = get_redis()
    payload = json.dumps(event, separators=(",", ":"), default=str)
    stream_id = await client.xadd(
        settings.redis_stream,
        {"payload": payload},
        maxlen=settings.stream_maxlen,
        approximate=True,
    )
    tenant = str(event["tenant_id"])
    await client.publish(
        f"{settings.redis_live_channel_prefix}:{tenant}", payload
    )
    return str(stream_id)
