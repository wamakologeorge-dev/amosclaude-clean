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


def test_chat_returns_amosclaud_contract_without_runtime(monkeypatch):
    monkeypatch.delenv("AMOSCLAUD_MODEL_URL", raising=False)
    monkeypatch.setenv("AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS", "false")
    response = request("POST", "/api/chat", json={"message": "Help me inspect this repository"})
    assert response.status_code == 200
    body = response.json()
    assert body["reply"]
    assert body["session_id"]
    assert body["timestamp"]
    assert body["provider"] == "amosclaud"
    assert "model runtime" in body["reply"].lower()


def test_chat_history_and_clear(monkeypatch):
    monkeypatch.delenv("AMOSCLAUD_MODEL_URL", raising=False)
    response = request("POST", "/api/chat", json={"message": "Run the tests"})
    session_id = response.json()["session_id"]
    history = request("GET", f"/api/chat/history/{session_id}")
    assert history.status_code == 200
    assert len(history.json()["history"]) == 2
    assert request("DELETE", f"/api/chat/history/{session_id}").status_code == 204
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
    assert body["provider"] == "amosclaud"
    assert body["task_id"]
    assert body["task_status"] in {"queued", "running", "failed"}


def test_chat_cannot_queue_pr_agent_without_owner_key(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "private-key")
    response = request("POST", "/api/chat", json={"message": "Repair the dashboard", "start_pr_task": True})
    assert response.status_code == 401


def test_chat_uses_self_hosted_amosclaud_runtime(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", "http://amosclaud-model:11434")
    monkeypatch.setenv("AMOSCLAUD_MODEL", "qwen2.5-coder:3b")
    monkeypatch.setenv("AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS", "false")

    from amoscloud_ai import provider

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "I am Amosclaud and the runtime is working."}}]}

    def fake_post(url, headers, json, timeout):
        captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(provider.httpx, "post", fake_post)
    response = request("POST", "/api/chat", json={"message": "hello"})
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "amosclaud"
    assert body["reply"] == "I am Amosclaud and the runtime is working."
    assert captured["url"] == "http://amosclaud-model:11434/v1/chat/completions"
    assert captured["json"]["model"] == "qwen2.5-coder:3b"
    assert captured["json"]["messages"][0]["role"] == "system"


def test_chat_rejects_invalid_platform_api_key(monkeypatch):
    monkeypatch.delenv("CHAT_REQUIRE_API_KEY", raising=False)
    response = request(
        "POST",
        "/api/chat",
        json={"message": "hello"},
        headers={"X-API-Key": "ak_not-a-real-issued-key-000000"},
    )
    assert response.status_code == 401


def test_chat_requires_platform_key_when_enforced(monkeypatch):
    monkeypatch.setenv("CHAT_REQUIRE_API_KEY", "true")
    response = request("POST", "/api/chat", json={"message": "hello"})
    assert response.status_code == 401
    assert "X-API-Key" in response.json()["detail"]

    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "owner-secret")
    monkeypatch.delenv("AMOSCLAUD_MODEL_URL", raising=False)
    response = request(
        "POST",
        "/api/chat",
        json={"message": "hello"},
        headers={"X-Amosclaud-Owner-Key": "owner-secret"},
    )
    assert response.status_code == 200
    assert response.json()["provider"] == "amosclaud"


def test_provider_status_is_owner_only(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "owner-secret")
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", "http://amosclaud-model:11434")
    assert request("GET", "/api/provider/status").status_code == 401
    response = request(
        "GET",
        "/api/provider/status",
        headers={"X-Amosclaud-Owner-Key": "owner-secret"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "amosclaud"
    assert body["self_hosted_configured"] is True
