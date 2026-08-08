from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4
import httpx


class AmosclaudLoggingClient:
    def __init__(self, endpoint: str, api_key: str, *, timeout: float = 10.0) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.client = httpx.Client(timeout=timeout, headers={"X-Amosclaud-Key": api_key})

    def event(self, *, message: str, service: str, level: str = "INFO", **context: Any) -> dict[str, Any]:
        return {
            "event_id": str(uuid4()), "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level.upper(), "message": message, "service": service, **context,
        }

    def send(self, event: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(f"{self.endpoint}/v1/logs", json=event)
        response.raise_for_status()
        return response.json()

    def send_batch(self, events: Iterable[dict[str, Any]]) -> dict[str, Any]:
        response = self.client.post(f"{self.endpoint}/v1/logs/batch", json={"events": list(events)})
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self.client.close()
