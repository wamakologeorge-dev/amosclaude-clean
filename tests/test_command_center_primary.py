"""The Command Center is the primary signed-in experience at /cloud/agent.

Every test here stays offline: DNS and TCP probes are stubbed, and no test
reaches a real model endpoint or a third-party API.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amoscloud_ai import main as main_module
from amoscloud_ai import model_runtime
from amoscloud_ai.api.routes import admin as admin_module

ROOT = Path(__file__).resolve().parents[1]
LEGACY_ROUTE = "/cloud/agent/legacy"


@pytest.fixture
def signed_in_client(monkeypatch) -> TestClient:
    """A client whose session cookie resolves to a real, active account."""
    monkeypatch.setattr(
        main_module,
        "get_user_from_session",
        lambda _token: {"id": 1, "name": "Owner", "is_admin": 0},
    )
    monkeypatch.setattr(admin_module, "is_session_suspended", lambda _token: False)
    client = TestClient(main_module.create_app())
    client.cookies.set("amos_session", "session-token")
    return client


@pytest.fixture
def anonymous_client() -> TestClient:
    return TestClient(main_module.create_app())


def test_cloud_agent_serves_the_command_center(signed_in_client):
    response = signed_in_client.get("/cloud/agent")

    assert response.status_code == 200
    assert "<h1>Command Center</h1>" in response.text
    assert "/static/command-center.js" in response.text
    assert "Turn on AmoModel" not in response.text
    assert "Check Autonomous and server" not in response.text


def test_legacy_route_still_serves_the_legacy_hub(signed_in_client):
    response = signed_in_client.get(LEGACY_ROUTE)

    assert response.status_code == 200
    assert "Runtime health" in response.text
    assert "Turn on AmoModel" in response.text
    assert "Turn off AmoModel" in response.text
    assert "Check Autonomous and server" in response.text
    assert "/static/amomodel-controls.js" in response.text


def test_command_center_route_still_serves_the_same_page(signed_in_client):
    primary = signed_in_client.get("/cloud/agent")
    command_center = signed_in_client.get("/command-center")

    assert command_center.status_code == 200
    assert "<h1>Command Center</h1>" in command_center.text
    assert command_center.text == primary.text


@pytest.mark.parametrize("path", ["/cloud/agent", LEGACY_ROUTE, "/command-center"])
def test_authenticated_pages_redirect_anonymous_visitors(anonymous_client, path):
    response = anonymous_client.get(path, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_command_center_keeps_repository_issue_and_agent_affordances():
    html = (ROOT / "web/command-center.html").read_text(encoding="utf-8")
    script = (ROOT / "web/command-center.js").read_text(encoding="utf-8")

    for element in (
        'id="repository-form"',
        'id="repository-select"',
        'id="issue-form"',
        'id="issue-list"',
        'id="agent-form"',
        'id="task-status"',
        'id="task-logs"',
        'id="task-checks"',
        'id="task-evidence"',
        'id="runtime-panel"',
    ):
        assert element in html

    for endpoint in (
        "/api/v1/repositories",
        "/issues",
        "/api/v1/agent/run",
        "/api/v1/pipelines/",
        "/branches",
        "/commits?branch=",
        "/pull-requests",
    ):
        assert endpoint in script


def test_command_center_replaces_amomodel_power_controls():
    html = (ROOT / "web/command-center.html").read_text(encoding="utf-8")
    script = (ROOT / "web/command-center.js").read_text(encoding="utf-8")

    for retired in (
        "Turn on AmoModel",
        "Turn off AmoModel",
        "Check Autonomous and server",
        "/api/v1/amomodel/power/on",
        "/api/v1/amomodel/power/off",
    ):
        assert retired not in html
        assert retired not in script
    assert "Runtime status" in html
    assert "/ready" in script
    assert LEGACY_ROUTE in html


def test_runtime_status_module_never_renders_the_raw_transport_detail():
    module = (ROOT / "web/runtime-status.js").read_text(encoding="utf-8")

    assert "blocker.remediation" in module
    assert "blocker.detail" not in module
    for code in ("dns_unresolved", "connection_refused", "unconfigured"):
        assert code in module


def _unresolvable(monkeypatch, hostname: str) -> None:
    def resolve(host: str, port: int):
        if host == hostname:
            raise socket.gaierror(-2, "Name or service not known")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, port))]

    monkeypatch.setattr(model_runtime, "_resolve_host", resolve)
    monkeypatch.setattr(model_runtime, "_tcp_connect", lambda *_a, **_k: None)


@pytest.fixture
def unreachable_model(monkeypatch):
    """A deployment whose only model endpoint has an unresolvable hostname."""
    for name in ("AMOSCLAUD_API_URL", "AMOSCLAUD_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", "https://model.internal:11434")
    _unresolvable(monkeypatch, "model.internal")
    model_runtime.reset_cache()
    yield
    model_runtime.reset_cache()


def _ready_payload(client: TestClient) -> dict:
    body = client.get("/ready").json()
    runtime = body["provider"]["model_runtime"]
    assert runtime["reachable"] is False
    assert runtime["blocker"]["code"] == model_runtime.DNS_UNRESOLVED
    return body


def test_readiness_gives_the_panel_actionable_remediation(
    anonymous_client, unreachable_model
):
    blocker = _ready_payload(anonymous_client)["provider"]["model_runtime"]["blocker"]

    assert "model.internal" in blocker["remediation"]
    assert "AMOSCLAUD_MODEL_URL" in blocker["remediation"]
    assert "Errno" not in blocker["remediation"]
    # The raw operating-system text still exists for the server log only.
    assert "Errno" in blocker["detail"]


def test_runtime_panel_renders_remediation_and_never_an_errno(
    anonymous_client, unreachable_model
):
    node = shutil.which("node")
    if not node:  # pragma: no cover - only on hosts without Node.js
        pytest.skip("node is required to execute the runtime status module")

    ready = _ready_payload(anonymous_client)
    script = (
        "const status = require(process.argv[1]);"
        "const summary = status.summarize(JSON.parse(process.argv[2]));"
        "process.stdout.write(JSON.stringify(summary));"
    )
    completed = subprocess.run(
        [node, "-e", script, str(ROOT / "web/runtime-status.js"), json.dumps(ready)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    summary = json.loads(completed.stdout)

    assert summary["reachable"] is False
    assert summary["code"] == model_runtime.DNS_UNRESOLVED
    assert summary["headline"] == (
        "Model hostname cannot be resolved from this deployment"
    )
    assert "Self-hosted Amosclaud model" in summary["activePath"]
    assert "model.internal" in summary["remediation"]
    assert "AMOSCLAUD_MODEL_URL" in summary["remediation"]
    assert "Errno" not in summary["message"]
    assert "repositories" in summary["nativeNote"]
    assert "No OpenAI or other external API key is required" in summary["noKeyNote"]
