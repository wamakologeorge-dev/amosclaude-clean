import json
import urllib.request
import urllib.error
from cli.config import CLIConfig

class AmosClient:
    def __init__(self):
        self.base_url = CLIConfig.API_URL.rstrip("/")

    def _request(self, method: str, path: str, data: dict = None) -> dict:
        url = f"{self.base_url}{path}"
        headers = {"Content-Type": "application/json"}
        req_data = None
        
        if data is not None:
            req_data = json.dumps(data).encode("utf-8")
            
        req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
        
        try:
            with urllib.request.urlopen(req, timeout=CLIConfig.TIMEOUT) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                error_body = json.loads(e.read().decode("utf-8"))
                return {"error": True, "status_code": e.code, "message": error_body.get("detail", str(e))}
            except Exception:
                return {"error": True, "status_code": e.code, "message": str(e)}
        except urllib.error.URLError as e:
            return {"error": True, "status_code": 503, "message": f"Could not connect to server at {self.base_url}: {e.reason}"}

    def get_status(self) -> dict:
        return self._request("GET", "/api/v1/status")

    def trigger_cmood_sync(self, file_path: str, action: str) -> dict:
        payload = {
            "file_path": file_path,
            "action": action,
            "agent_id": CLIConfig.AGENT_ID
        }
        return self._request("POST", "/api/v1/cmood/sync", payload)

    def get_jobs(self) -> dict:
        return self._request("GET", "/api/v1/cmood/jobs")
