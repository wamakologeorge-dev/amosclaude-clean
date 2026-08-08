from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from uuid import UUID

import asyncpg

from app.fingerprint import fingerprint
from app.fixee_client import FixeeClient
from app.incidents import IncidentStore

DATABASE_URL = os.getenv("AMOSCLAUD_LOGGING_DATABASE_URL", "postgresql://amosclaud:amosclaud@postgres:5432/amosclaud_logs")
POLL_SECONDS = float(os.getenv("AMOSCLAUD_LOGGING_ALERT_POLL_SECONDS", "5"))


async def run() -> None:
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    store = IncidentStore(pool)
    fixee = FixeeClient()
    cursor_time = datetime.now(timezone.utc)
    cursor_id = UUID(int=0)
    try:
        while True:
            rows = await pool.fetch(
                """
                SELECT event_id, timestamp, ingested_at, level, message, service, environment,
                       tenant_id, user_id, request_id, trace_id, tags, metadata
                FROM logs
                WHERE (ingested_at, event_id) > ($1, $2::uuid)
                  AND level IN ('ERROR', 'CRITICAL')
                ORDER BY ingested_at ASC, event_id ASC
                LIMIT 1000
                """,
                cursor_time, cursor_id,
            )
            for row in rows:
                event = dict(row)
                incident = await store.upsert(event, fingerprint(event))
                if event["level"] == "CRITICAL" or incident["occurrence_count"] >= 5:
                    await fixee.propose(incident)
                cursor_time = event["ingested_at"]
                cursor_id = event["event_id"]
            await asyncio.sleep(POLL_SECONDS)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(run())
