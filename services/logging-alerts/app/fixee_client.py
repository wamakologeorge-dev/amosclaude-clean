from __future__ import annotations

import json
import os
from typing import Any
import httpx


class FixeeClient:
    def __init__(self) -> None:
        self.url = os.getenv("AMOSCLAUD_FIXEE_URL", "").rstrip("/")
        self.token = os.getenv("AMOSCLAUD_FIXEE_TOKEN", "")

    async def propose(self, incident: dict[str, Any]) -> dict[str, Any] | None:
        if not self.url:
            return None
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        payload = {
            "mode": "diagnose-and-propose",
            "allow_execution": False,
            "incident": json.loads(json.dumps(incident, default=str)),
            "safety": {
                "commit": False, "push": False, "deploy": False,
                "requires_explicit_approval": True,
            },
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(f"{self.url}/api/v1/incidents/propose", json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
