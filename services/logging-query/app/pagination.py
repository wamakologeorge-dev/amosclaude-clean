from __future__ import annotations

import base64
import json
from datetime import datetime


def encode_cursor(timestamp: datetime, event_id: str) -> str:
    raw = json.dumps([timestamp.isoformat(), event_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    padding = "=" * (-len(cursor) % 4)
    timestamp, event_id = json.loads(base64.urlsafe_b64decode(cursor + padding))
    return datetime.fromisoformat(timestamp), str(event_id)
