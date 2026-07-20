"""HTTP client for the Amosclaud Autonomous platform."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from cli.config import CLIConfig


class AmosClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self.base_url = (base_url or CLIConfig.API_URL).rstrip("/")
        self.api_key = CLIConfig.API_KEY if api_key is None else api_key

    def _request(self, method: str, path: str, data: dict[str, Any] | None = None):
        url = f"{self.base_url}{path}"
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            headers["X-Amosclaud-API-Key"] = self.api_key
        req_data = json.dumps(data).encode("utf-8") if data is not None else None
        request = urllib.request.Request(url, data=req_data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(request, timeout=CLIConfig.TIMEOUT) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            try:
                error_body = json.loads(error.read().decode("utf-8"))
                message = error_body.get("detail") or error_body.get("message") or str(error)
            except (UnicodeDecodeError, json.JSONDecodeError):
                message = str(error)
            return {"error": True, "status_code": error.code, "message": message}
        except urllib.error.URLError as error:
            return {
                "error": True,
                "status_code": 503,
                "message": f"Could not connect to Amosclaud at {self.base_url}: {error.reason}",
            }

    def get_status(self) -> dict:
        return self._request("GET", "/health")

    def run_agent(
        self,
        objective: str,
        *,
        mode: str = "plan",
        repository_id: str | None = None,
        branch: str | None = None,
        authorized_writes: bool = False,
    ) -> dict:
        payload = {
            "mode": mode,
            "objective": objective,
            "branch": branch or CLIConfig.DEFAULT_BRANCH,
            "metadata": {
                "agent_id": CLIConfig.AGENT_ID,
                "repository_id": repository_id or CLIConfig.REPOSITORY_ID or None,
                "authorized_writes": authorized_writes,
                "source": "amosclaud-cli",
            },
        }
        return self._request("POST", "/api/v1/agent/run", payload)

    def trigger_sync(self, file_path: str, action: str) -> dict:
        resolved = Path(file_path).expanduser().resolve()
        payload = {
            "trigger": "cli-sync",
            "branch": CLIConfig.DEFAULT_BRANCH,
            "payload": {
                "file_path": str(resolved),
                "action": action,
                "agent_id": CLIConfig.AGENT_ID,
            },
        }
        return self._request("POST", "/api/v1/pipelines", payload)

    # Backward-compatible name retained for older scripts.
    trigger_cmood_sync = trigger_sync

    def get_jobs(self) -> dict:
        pipelines = self._request("GET", "/api/v1/pipelines")
        if isinstance(pipelines, dict) and pipelines.get("error"):
            return pipelines
        jobs = []
        for pipeline in pipelines if isinstance(pipelines, list) else []:
            payload = pipeline.get("payload", {}) if isinstance(pipeline, dict) else {}
            jobs.append(
                {
                    "job_id": pipeline.get("id", "N/A"),
                    "file_path": payload.get("file_path", pipeline.get("branch", "main")),
                    "action": pipeline.get("trigger", "pipeline"),
                    "status": pipeline.get("status", "unknown"),
                }
            )
        return {"jobs": jobs}

    def list_repositories(self) -> dict | list:
        return self._request("GET", "/api/v1/repositories")
