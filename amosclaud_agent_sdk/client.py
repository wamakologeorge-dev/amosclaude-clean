"""Dependency-free client for Amosclaud Autonomous on Amosclaud.com."""
from __future__ import annotations
import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from .errors import AmosclaudSDKError

class AmosclaudAgentError(AmosclaudSDKError):
    """A safe, user-facing Amosclaud API failure."""

@dataclass(slots=True)
class AmosclaudAgentClient:
    """Connect Python to the governed Amosclaud agent runtime."""
    base_url: str = "https://www.amosclaud.com"
    api_key: str | None = None
    session_cookie: str | None = None
    timeout: float = 30.0

    def __post_init__(self) -> None:
        self.base_url = (self.base_url or "https://www.amosclaud.com").rstrip("/")
        self.api_key = self.api_key or os.getenv("AMOSCLAUD_API_KEY")
        self.session_cookie = self.session_cookie or os.getenv("AMOSCLAUD_SESSION")

    def profile(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/agent")

    def readiness(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/agent/readiness")

    def run(self, objective: str, *, mode: str = "autonomous-check", branch: str = "main", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        if not objective.strip():
            raise ValueError("objective is required")
        return self._request("POST", "/api/v1/agent/run", {"objective": objective, "mode": mode, "branch": branch, "metadata": dict(metadata or {})})

    def pipeline(self, pipeline_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/pipelines/{quote(pipeline_id, safe='')}")

    def run_and_wait(self, objective: str, *, mode: str = "autonomous-check", branch: str = "main", metadata: dict[str, Any] | None = None, poll_seconds: float = 1.0, max_wait_seconds: float = 300.0) -> dict[str, Any]:
        accepted = self.run(objective, mode=mode, branch=branch, metadata=metadata)
        if accepted.get("status") in {"success", "failed", "cancelled"}:
            return accepted
        pipeline_id = str(accepted.get("pipeline_id") or "")
        if not pipeline_id:
            raise AmosclaudAgentError("Amosclaud did not return a pipeline identifier")
        deadline = time.monotonic() + max_wait_seconds
        while time.monotonic() < deadline:
            result = self.pipeline(pipeline_id)
            if result.get("status") in {"success", "failed", "cancelled"}:
                return result
            time.sleep(max(0.1, poll_seconds))
        raise AmosclaudAgentError(f"Pipeline {pipeline_id} did not finish within {max_wait_seconds:g} seconds")

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Accept": "application/json", "User-Agent": "amosclaud-agent-sdk"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.session_cookie:
            headers["Cookie"] = f"amos_session={self.session_cookie}"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        request = Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode()
        except HTTPError as error:
            raw = error.read().decode(errors="replace")
            try:
                detail = json.loads(raw).get("detail", raw)
            except json.JSONDecodeError:
                detail = raw
            raise AmosclaudAgentError(f"Amosclaud request failed ({error.code}): {detail}") from error
        except (URLError, TimeoutError) as error:
            raise AmosclaudAgentError(f"Cannot reach {self.base_url}: {error}") from error
        try:
            result = json.loads(raw or "{}")
        except json.JSONDecodeError as error:
            raise AmosclaudAgentError("Amosclaud returned a non-JSON response") from error
        if not isinstance(result, dict):
            raise AmosclaudAgentError("Amosclaud returned an invalid response contract")
        return result
