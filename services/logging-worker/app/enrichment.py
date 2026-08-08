from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any


def enrich(event: dict[str, Any], stream_id: str) -> dict[str, Any]:
    enriched = dict(event)
    enriched["ingested_at"] = datetime.now(timezone.utc).isoformat()
    enriched["redis_stream_id"] = stream_id
    fingerprint_source = "|".join(
        [str(event.get("tenant_id", "")), str(event.get("service", "")), str(event.get("level", "")), str(event.get("message", ""))]
    )
    enriched["event_fingerprint"] = hashlib.sha256(
        fingerprint_source.encode("utf-8", errors="replace")
    ).hexdigest()
    return enriched
