"""Contract tests for the shared Android and web chat API."""

from __future__ import annotations

import asyncio

import httpx

from amoscloud_ai.main import create_app

app = create_app()


def request(method: str, path: str, **kwargs):
    async def send():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def test_chat_returns_android_contract_without_provider_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = request("POST", "/api/chat", json={"message": "Help me inspect this repository"})
    assert response.status_code == 200
    body = response.json()
    assert body["reply"]
    assert body["session_id"]
    assert body["timestamp"]
    assert body["provider"] == "offline"


def test_chat_history_and_clear():
    response = request("POST", "/api/chat", json={"message": "Run the tests"})
    session_id = response.json()["session_id"]
    history = request("GET", f"/api/chat/history/{session_id}")
    assert history.status_code == 200
    assert len(history.json()["history"]) == 2
    cleared = request("DELETE", f"/api/chat/history/{session_id}")
    assert cleared.status_code == 204
    assert request("GET", f"/api/chat/history/{session_id}").json()["history"] == []


def test_capabilities_describe_connected_repository_agent():
    response = request("GET", "/api/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert "repository_instruction_analysis" in body["capabilities"]
    assert body["repository_scope"] == "wamakologeorge-dev/amosclaude-clean"


def test_owner_chat_command_queues_pr_agent_work(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "private-key")
    response = request(
        "POST",
        "/api/chat",
        headers={"X-Amosclaud-Owner-Key": "private-key"},
        json={"message": "Repair the dashboard", "start_pr_task": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "pr-agent"
    assert body["task_id"]
    assert body["task_status"] in {"queued", "running", "failed"}
    assert body["task_url"].endswith(body["task_id"])


def test_chat_cannot_queue_pr_agent_without_owner_key(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "private-key")
    response = request("POST", "/api/chat", json={"message": "Repair the dashboard", "start_pr_task": True})
    assert response.status_code == 401


def test_chat_always_uses_platform_server_key(monkeypatch):
    """The platform answers with its own key; clients never supply provider keys."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-platform-key")

    from amoscloud_ai.api.routes import chat as chat_module

    monkeypatch.setattr(chat_module, "_openai_reply", lambda history, key=None: f"openai:{key}")

    response = request("POST", "/api/chat", json={"message": "hello"})
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "openai"
    assert body["reply"] == "openai:sk-platform-key"


def test_chat_rejects_invalid_platform_api_key(monkeypatch):
    """A presented Amosclaud API key must be one the owner actually issued."""
    monkeypatch.delenv("CHAT_REQUIRE_API_KEY", raising=False)
    response = request(
        "POST",
        "/api/chat",
        json={"message": "hello"},
        headers={"X-API-Key": "ak_not-a-real-issued-key-000000"},
    )
    assert response.status_code == 401


def test_chat_accepts_platform_issued_api_key(tmp_path, monkeypatch):
    """Keys created by the owner in the API-key manager grant client access."""
    monkeypatch.setenv("API_KEY_DATABASE_URL", f"sqlite:///{tmp_path}/keys.db")

    import importlib

    import api_key_manager.database as km_database
    import api_key_manager.models as km_models
    import api_key_manager.crud as km_crud
    import api_key_manager.auth as km_auth
    import api_key_manager.schemas as km_schemas

    importlib.reload(km_database)
    importlib.reload(km_models)
    km_models.Base.metadata.create_all(bind=km_database.engine)

    from amoscloud_ai.api.routes import chat as chat_module

    monkeypatch.setattr(chat_module, "_key_manager_ready", True)
    monkeypatch.setattr(km_auth, "get_db", km_database.get_db)

    plain_key = km_auth.generate_api_key_string()
    db = km_database.SessionLocal()
    try:
        km_crud.create_api_key(
            db,
            km_schemas.ApiKeyCreate(description="client org key"),
            plain_key,
            km_auth.api_key_lookup_prefix(plain_key),
        )
    finally:
        db.close()

    monkeypatch.setattr(chat_module, "SessionLocal", km_database.SessionLocal, raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    import api_key_manager.database

    monkeypatch.setattr(api_key_manager.database, "SessionLocal", km_database.SessionLocal)

    response = request(
        "POST",
        "/api/chat",
        json={"message": "hello"},
        headers={"X-API-Key": plain_key},
    )
    assert response.status_code == 200
    assert response.json()["provider"] == "offline"


def test_chat_requires_platform_key_when_enforced(monkeypatch):
    """CHAT_REQUIRE_API_KEY=true locks chat to owner + issued client keys."""
    monkeypatch.setenv("CHAT_REQUIRE_API_KEY", "true")
    response = request("POST", "/api/chat", json={"message": "hello"})
    assert response.status_code == 401
    assert "X-API-Key" in response.json()["detail"]

    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "owner-secret")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = request(
        "POST",
        "/api/chat",
        json={"message": "hello"},
        headers={"X-Amosclaud-Owner-Key": "owner-secret"},
    )
    assert response.status_code == 200
    assert response.json()["provider"] == "offline"


def test_chat_offline_reply_does_not_ask_for_provider_keys(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = request("POST", "/api/chat", json={"message": "hello"})
    body = response.json()
    assert body["provider"] == "offline"
    assert "X-LLM-API-Key" not in body["reply"]
    assert "ANTHROPIC_API_KEY" not in body["reply"]
