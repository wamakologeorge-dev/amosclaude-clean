from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

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
    cursor = datetime.now(timezone.utc)
    try:
        while True:
            rows = await pool.fetch(
                """
                SELECT event_id, timestamp, level, message, service, environment,
                       tenant_id, user_id, request_id, trace_id, tags, metadata
                FROM logs
                WHERE ingested_at >= $1 AND level IN ('ERROR', 'CRITICAL')
                ORDER BY ingested_at ASC
                LIMIT 1000
                """,
                cursor,
            )
            for row in rows:
                event = dict(row)
                incident = await store.upsert(event, fingerprint(event))
                if event["level"] == "CRITICAL" or incident["occurrence_count"] >= 5:
                    await fixee.propose(incident)
                cursor = max(cursor, event["timestamp"])
            await asyncio.sleep(POLL_SECONDS)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(run())
