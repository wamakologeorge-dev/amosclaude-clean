import httpx
import pytest
from fastapi.testclient import TestClient
from pathlib import Path

from amoscloud_ai import model_station


def test_health_is_truthful_when_upstream_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        model_station, "_complete", lambda body: (_ for _ in ()).throw(RuntimeError("offline"))
    )
    client = TestClient(model_station.app)
    response = client.get("/ready")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is False
    assert payload["status"] == "not_ready"


def test_chat_completion_uses_real_backend_result(monkeypatch):
    monkeypatch.setattr(model_station, "_complete", lambda body: ("verified model reply", 12))
    client = TestClient(model_station.app)
    response = client.post(
        "/v1/chat/completions",
        json={"model": "amosclaud-test", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == "verified model reply"
    assert payload["station"]["latency_ms"] == 12


def test_station_token_is_enforced(monkeypatch):
    monkeypatch.setattr(model_station, "STATION_TOKEN", "secret-token")
    client = TestClient(model_station.app)
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 401
    assert client.get("/v1/models").status_code == 401


def test_amosclaud_api_key_is_accepted(monkeypatch):
    monkeypatch.setattr(model_station, "STATION_TOKEN", "")
    monkeypatch.setattr(model_station, "AMOSCLAUD_API_KEY", "amos_test_key")
    monkeypatch.setattr(model_station, "_probe", lambda: {"status": "ready", "ready": True})
    client = TestClient(model_station.app)
    assert (
        client.get("/ready", headers={"Authorization": "Bearer amos_test_key"}).status_code == 200
    )
    assert client.get("/v1/models", headers={"X-API-Key": "amos_test_key"}).status_code == 200


def test_owned_folder_model_is_created_when_upstream_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(model_station, "BACKEND", "ollama")
    monkeypatch.setattr(model_station, "FOLDER_FALLBACK_ENABLED", True)
    monkeypatch.setattr(model_station, "FOLDER_MODEL_ROOT", Path(tmp_path / "owned-model"))
    monkeypatch.setattr(model_station, "_folder_model_instance", None)
    monkeypatch.setattr(
        model_station,
        "_ollama_completion",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("upstream missing")),
    )
    reply, _latency = model_station._complete(
        model_station.CompletionRequest(
            messages=[model_station.Message(role="user", content="Build safely")],
            max_tokens=12,
        )
    )
    assert reply
    assert model_station._last_runtime == "folder-native-fallback"
    assert (tmp_path / "owned-model" / "checkpoints" / "current.json").exists()


def test_json_payload_rejects_plain_text_success_response():
    response = httpx.Response(
        200,
        headers={"content-type": "text/plain"},
        text="proxy returned an HTML or text response",
    )

    with pytest.raises(RuntimeError, match="non-JSON content"):
        model_station._json_payload(response, "Test upstream")


def test_json_payload_rejects_invalid_json_success_response():
    response = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        text="not valid json",
    )

    with pytest.raises(RuntimeError, match="invalid JSON"):
        model_station._json_payload(response, "Test upstream")
