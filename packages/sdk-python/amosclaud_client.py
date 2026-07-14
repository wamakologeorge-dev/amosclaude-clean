"""Dependency-light Amosclaud Developer API client."""

from __future__ import annotations

import json
import urllib.request


class AmosclaudClient:
    def __init__(self, api_key: str, base_url: str = "https://amosclaud.com/api/v1"):
        if not api_key:
            raise ValueError("api_key is required")
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def _request(self, method: str, path: str, payload: dict | None = None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            self.base_url + path, data=data, headers=self.headers, method=method
        )
        with urllib.request.urlopen(
            request, timeout=60
        ) as response:  # nosec B310 - caller controls trusted base URL
            return json.load(response)

    def create_task(self, objective: str, **options):
        return self._request("POST", "/tasks", {"objective": objective, **options})

    def get_task(self, task_id: str):
        return self._request("GET", f"/tasks/{task_id}")

    def list_tasks(self):
        return self._request("GET", "/tasks")
