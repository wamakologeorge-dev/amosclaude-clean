from __future__ import annotations

import json
from typing import Any
import asyncpg


class IncidentStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def upsert(self, event: dict[str, Any], fingerprint: str) -> dict[str, Any]:
        row = await self.pool.fetchrow(
            """
            INSERT INTO incidents (
                tenant_id, fingerprint, severity, service, title, status,
                first_seen_at, last_seen_at, occurrence_count, sample_event
            ) VALUES ($1, $2, $3, $4, $5, 'open', now(), now(), 1, $6::jsonb)
            ON CONFLICT (tenant_id, fingerprint) DO UPDATE SET
                last_seen_at = now(), occurrence_count = incidents.occurrence_count + 1,
                severity = EXCLUDED.severity, sample_event = EXCLUDED.sample_event
            RETURNING *
            """,
            event["tenant_id"], fingerprint, event["level"], event["service"],
            str(event["message"])[:300], json.dumps(event, default=str),
        )
        return dict(row)
