from __future__ import annotations

import json
from typing import Any

import asyncpg


class LogStorage:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=10)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    async def write(self, event: dict[str, Any]) -> None:
        if self.pool is None:
            raise RuntimeError("Storage is not connected")
        await self.pool.execute(
            """
            INSERT INTO logs (
                event_id, timestamp, ingested_at, level, message, service,
                environment, tenant_id, user_id, request_id, trace_id,
                tags, metadata, schema_version, event_fingerprint, redis_stream_id
            ) VALUES (
                $1::uuid, $2::timestamptz, $3::timestamptz, $4, $5, $6,
                $7, $8, $9, $10, $11, $12::jsonb, $13::jsonb, $14, $15, $16
            ) ON CONFLICT (event_id) DO NOTHING
            """,
            event["event_id"], event["timestamp"], event["ingested_at"],
            event["level"], event["message"], event["service"],
            event.get("environment", "development"), event["tenant_id"],
            event.get("user_id"), event.get("request_id"), event.get("trace_id"),
            json.dumps(event.get("tags", {})), json.dumps(event.get("metadata", {})),
            event.get("schema_version", "1.0"), event["event_fingerprint"],
            event["redis_stream_id"],
        )
