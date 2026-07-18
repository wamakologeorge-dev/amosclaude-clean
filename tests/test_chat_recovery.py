from fastapi.testclient import TestClient

from amoscloud_ai.api.routes import chat
from amoscloud_ai.main import create_app


def test_chat_returns_json_when_provider_is_offline(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = TestClient(create_app())

    response = client.post(
        "/api/chat",
        json={"message": "hello", "start_pr_task": False, "base_branch": "main"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["reply"]
    assert body["provider"] == "offline"


def test_chat_recovers_from_unexpected_provider_error(monkeypatch):
    monkeypatch.setattr(chat, "_resolve_provider", lambda: ("openai", "test-key"))

    async def explode(*_args, **_kwargs):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(chat.asyncio, "to_thread", explode)
    client = TestClient(create_app(), raise_server_exceptions=False)

    response = client.post(
        "/api/chat",
        json={"message": "keep working", "start_pr_task": False, "base_branch": "main"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["provider"] == "recovery"
    assert "temporarily unavailable" in body["reply"]
