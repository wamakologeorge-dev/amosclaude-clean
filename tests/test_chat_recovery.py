from fastapi.testclient import TestClient

from amoscloud_ai import provider
from amoscloud_ai.main import create_app


def test_chat_returns_json_when_model_runtime_is_unconfigured(monkeypatch):
    monkeypatch.delenv("AMOSCLAUD_MODEL_URL", raising=False)
    monkeypatch.setenv("AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS", "false")
    client = TestClient(create_app())

    response = client.post(
        "/api/chat",
        json={"message": "hello", "start_pr_task": False, "base_branch": "main"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["reply"]
    assert body["provider"] == "amosclaud"
    assert "model runtime is not connected" in body["reply"]


def test_chat_recovers_from_unexpected_model_runtime_error(monkeypatch):
    def explode(*_args, **_kwargs):
        raise RuntimeError("model runtime exploded")

    monkeypatch.setattr(provider, "reply", explode)
    client = TestClient(create_app(), raise_server_exceptions=False)

    response = client.post(
        "/api/chat",
        json={"message": "keep working", "start_pr_task": False, "base_branch": "main"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["provider"] == "amosclaud"
    assert "could not reach its model runtime" in body["reply"]
    assert "not completed" in body["reply"]
