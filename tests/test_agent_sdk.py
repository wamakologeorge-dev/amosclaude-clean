import json
import subprocess
import sys

from amosclaud_agent_sdk.client import AmosclaudAgentClient


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self.payload).encode()


def test_sdk_connects_to_hosted_agent_with_bearer_key(monkeypatch):
    captured = {}

    def open_request(request, timeout):
        captured.update(
            url=request.full_url,
            authorization=request.headers["Authorization"],
            payload=json.loads(request.data),
            timeout=timeout,
        )
        return Response({"accepted": True, "pipeline_id": "pipeline-1"})

    monkeypatch.setattr("amosclaud_agent_sdk.client.urlopen", open_request)
    result = AmosclaudAgentClient(api_key="amos_aut_test", timeout=12).run(
        "Inspect repository", mode="build"
    )
    assert result["pipeline_id"] == "pipeline-1"
    assert captured["url"] == "http://www.amosclaud.com/api/v1/agent/run"
    assert captured["authorization"] == "Bearer amos_aut_test"
    assert captured["payload"]["mode"] == "build"


def test_admin_session_does_not_need_api_key(monkeypatch):
    captured = {}

    def open_request(request, timeout):
        captured.update(
            cookie=request.headers["Cookie"],
            authorization=request.headers.get("Authorization"),
        )
        return Response({"ready": True})

    monkeypatch.setattr("amosclaud_agent_sdk.client.urlopen", open_request)
    assert AmosclaudAgentClient(session_cookie="admin-session").readiness()["ready"] is True
    assert captured == {"cookie": "amos_session=admin-session", "authorization": None}


def test_build_script_help_never_runs_an_installer():
    result = subprocess.run(
        [sys.executable, "scripts/build_wheel.py", "--help"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "skip-sdist" in result.stdout
    source = open("scripts/build_wheel.py", encoding="utf-8").read()
    assert "curl" not in source
    assert "install.sh" not in source
