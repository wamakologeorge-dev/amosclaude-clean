"""The Autonomous kernel must use real ollama inference — never an echo stub.

These tests run a local HTTP stub that speaks the ollama /api/chat protocol,
so they prove the wiring (URL, auth headers, payload, parsing, honest
failures) without needing a live model station.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.amosclaud_os.intelligence.model_engine import ModelEngine

STUB_ANSWER = "1. Inspect the repository.\n2. Apply the bounded fix.\n3. Verify."


class _StubStation(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def do_POST(self):  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "body": body,
            }
        )
        payload = json.dumps(
            {"model": body.get("model"), "message": {"role": "assistant", "content": STUB_ANSWER}}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # keep test output clean
        return


@pytest.fixture()
def stub_station():
    _StubStation.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubStation)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_respond_returns_station_answer_not_an_echo(stub_station, monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", stub_station)
    monkeypatch.setenv("AMOSCLAUD_MODEL_TOKEN", "amos-token-123")
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    engine = ModelEngine()
    prompt = "Explain what the security middleware protects."
    result = engine.respond(prompt)
    assert not result.failed
    assert result.text == STUB_ANSWER
    assert result.text != prompt, "the old echo stub must never return"
    assert _StubStation.requests[0]["path"] == "/api/chat"
    assert _StubStation.requests[0]["body"]["stream"] is False


def test_amosclaud_token_wins_and_is_sent_as_bearer(stub_station, monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", stub_station)
    monkeypatch.setenv("AMOSCLAUD_MODEL_TOKEN", "amos-token-123")
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-key-456")
    engine = ModelEngine()
    assert engine.auth_mode == "amosclaud-token"
    engine.respond("hello station")
    assert _StubStation.requests[0]["authorization"] == "Bearer amos-token-123"


def test_ollama_api_key_is_used_when_no_amosclaud_token(stub_station, monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", stub_station)
    monkeypatch.delenv("AMOSCLAUD_MODEL_TOKEN", raising=False)
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-key-456")
    engine = ModelEngine()
    assert engine.auth_mode == "ollama-api-key"
    engine.respond("hello station")
    assert _StubStation.requests[0]["authorization"] == "Bearer ollama-key-456"


def test_missing_station_is_an_honest_failure(monkeypatch):
    monkeypatch.delenv("AMOSCLAUD_MODEL_URL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    engine = ModelEngine()
    prompt = "Draft a plan."
    result = engine.respond(prompt)
    assert result.failed
    assert result.error == "model_station_not_configured"
    assert result.text != prompt


def test_unreachable_station_is_an_honest_failure(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", "http://127.0.0.1:9")  # closed port
    monkeypatch.setenv("AMOSCLAUD_MODEL_TIMEOUT", "5")
    engine = ModelEngine()
    prompt = "Draft a plan."
    result = engine.respond(prompt)
    assert result.failed
    assert result.error and result.error.startswith("station_unreachable")
    assert result.text != prompt


def test_kernel_execute_attaches_model_plan_and_evidence(stub_station, monkeypatch, tmp_path):
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", stub_station)
    monkeypatch.setenv("AMOSCLAUD_MODEL_TOKEN", "amos-token-123")
    from src.amosclaud_os.kernel import AutonomousKernel

    kernel = AutonomousKernel(tmp_path)
    outcome = kernel.execute(objective="Plan a tiny documentation improvement.", mode="plan")
    assert outcome["model"]["engaged"] is True
    assert outcome["model"]["auth"] == "amosclaud-token"
    evidence = " ".join(str(item) for item in outcome.get("evidence", []))
    assert "Model plan" in evidence
    assert STUB_ANSWER.splitlines()[0] in evidence


def test_kernel_reports_honestly_when_station_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("AMOSCLAUD_MODEL_URL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    from src.amosclaud_os.kernel import AutonomousKernel

    kernel = AutonomousKernel(tmp_path)
    outcome = kernel.execute(objective="Plan a tiny documentation improvement.", mode="plan")
    assert outcome["model"]["engaged"] is False
    assert outcome["model"]["error"] == "model_station_not_configured"
