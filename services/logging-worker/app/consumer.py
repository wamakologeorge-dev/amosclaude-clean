from __future__ import annotations

import asyncio
import json
import os
import socket

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.enrichment import enrich
from app.retry import RetryPolicy
from app.sanitizer import sanitize
from app.storage import LogStorage

REDIS_URL = os.getenv("AMOSCLAUD_LOGGING_REDIS_URL", "redis://redis:6379/0")
DATABASE_URL = os.getenv("AMOSCLAUD_LOGGING_DATABASE_URL", "postgresql://amosclaud:amosclaud@postgres:5432/amosclaud_logs")
STREAM = os.getenv("AMOSCLAUD_LOGGING_REDIS_STREAM", "amosclaud:logs")
GROUP = os.getenv("AMOSCLAUD_LOGGING_CONSUMER_GROUP", "logging-workers")
DEAD_STREAM = os.getenv("AMOSCLAUD_LOGGING_DEAD_STREAM", "amosclaud:logs:dead")
CONSUMER = os.getenv("HOSTNAME", socket.gethostname())


async def ensure_group(redis: Redis) -> None:
    try:
        await redis.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def run() -> None:
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    storage = LogStorage(DATABASE_URL)
    policy = RetryPolicy()
    await storage.connect()
    await ensure_group(redis)
    try:
        while True:
            response = await redis.xreadgroup(
                GROUP, CONSUMER, {STREAM: ">"}, count=100, block=5000
            )
            for _stream_name, messages in response:
                for stream_id, fields in messages:
                    attempts = int(fields.get("attempts", "1"))
                    try:
                        raw = json.loads(fields["payload"])
                        event = enrich(sanitize(raw), stream_id)
                        await storage.write(event)
                        await redis.xack(STREAM, GROUP, stream_id)
                    except Exception as exc:
                        if policy.should_dead_letter(attempts):
                            await redis.xadd(DEAD_STREAM, {
                                "payload": fields.get("payload", "{}"),
                                "source_stream_id": stream_id,
                                "attempts": str(attempts),
                                "error": str(exc)[:2000],
                            })
                            await redis.xack(STREAM, GROUP, stream_id)
                        else:
                            await asyncio.sleep(policy.delay(attempts))
                            await redis.xadd(STREAM, {
                                "payload": fields.get("payload", "{}"),
                                "attempts": str(attempts + 1),
                            })
                            await redis.xack(STREAM, GROUP, stream_id)
    finally:
        await storage.close()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(run())
