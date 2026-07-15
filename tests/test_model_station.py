from fastapi.testclient import TestClient

from amoscloud_ai import model_station


def test_health_is_truthful_when_upstream_is_unavailable(monkeypatch):
    monkeypatch.setattr(model_station, "_complete", lambda body: (_ for _ in ()).throw(RuntimeError("offline")))
    client = TestClient(model_station.app)
    response = client.get("/health")
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
    assert client.get("/health").status_code == 401
