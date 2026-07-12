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


def test_chat_uses_client_supplied_llm_key_for_provider_selection(monkeypatch):
    """External clients bring their own key; the platform never asks the owner for one."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    from amoscloud_ai.api.routes import chat as chat_module

    monkeypatch.setattr(chat_module, "_anthropic_reply", lambda history, key=None: f"anthropic:{bool(key)}")
    monkeypatch.setattr(chat_module, "_openai_reply", lambda history, key=None: f"openai:{bool(key)}")

    response = request(
        "POST",
        "/api/chat",
        json={"message": "hello"},
        headers={"X-LLM-API-Key": "sk-ant-client-key"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "anthropic"
    assert body["reply"] == "anthropic:True"

    response = request(
        "POST",
        "/api/chat",
        json={"message": "hello"},
        headers={"X-LLM-API-Key": "sk-client-key", "X-LLM-Provider": "openai"},
    )
    body = response.json()
    assert body["provider"] == "openai"
    assert body["reply"] == "openai:True"


def test_chat_offline_without_any_key_mentions_byok(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = request("POST", "/api/chat", json={"message": "hello"})
    body = response.json()
    assert body["provider"] == "offline"
    assert "X-LLM-API-Key" in body["reply"]
