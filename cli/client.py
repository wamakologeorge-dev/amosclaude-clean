import json
import urllib.error
import urllib.request

from cli.config import CLIConfig


class AmosClient:
    def __init__(self):
        self.base_url = CLIConfig.API_URL.rstrip("/")

    def _request(self, method: str, path: str, data: dict | None = None):
        url = f"{self.base_url}{path}"
        headers = {"Content-Type": "application/json"}
        req_data = json.dumps(data).encode("utf-8") if data is not None else None
        request = urllib.request.Request(url, data=req_data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(request, timeout=CLIConfig.TIMEOUT) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            try:
                error_body = json.loads(error.read().decode("utf-8"))
                message = error_body.get("detail", str(error))
            except Exception:
                message = str(error)
            return {"error": True, "status_code": error.code, "message": message}
        except urllib.error.URLError as error:
            return {
                "error": True,
                "status_code": 503,
                "message": f"Could not connect to server at {self.base_url}: {error.reason}",
            }

    def get_status(self) -> dict:
        """Read the real Amosclaud server health endpoint."""
        return self._request("GET", "/health")

    def trigger_cmood_sync(self, file_path: str, action: str) -> dict:
        """Run synchronization through the persistent Amosclaud pipeline engine."""
        payload = {
            "trigger": "cli-sync",
            "branch": "main",
            "payload": {
                "file_path": file_path,
                "action": action,
                "agent_id": CLIConfig.AGENT_ID,
            },
        }
        return self._request("POST", "/api/v1/pipelines", payload)

    def get_jobs(self) -> dict:
        """Read real persisted pipeline jobs and preserve the CLI's jobs response shape."""
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
