from __future__ import annotations

import asyncio
import time

import httpx

from amoscloud_ai import provider
from amoscloud_ai.api.routes import first_party_chat
from amoscloud_ai.main import create_app

app = create_app()


def request(method: str, path: str, **kwargs):
    async def send():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def test_chat_exposes_amosclaud_as_provider(monkeypatch):
    monkeypatch.delenv("AMOSCLAUD_MODEL_URL", raising=False)
    monkeypatch.setenv("AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS", "false")

    response = request("POST", "/api/chat", json={"message": "Hello"})

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "amosclaud"
    assert "model runtime is not connected" in body["reply"]


def test_workspace_chat_propagates_its_deadline_to_provider(monkeypatch):
    captured = {}

    def fake_reply(_history, _system_prompt, *, timeout=None):
        captured["timeout"] = timeout
        return provider.ProviderResult(reply="Ready.", runtime="test")

    monkeypatch.setattr(provider, "reply", fake_reply)
    monkeypatch.setattr(first_party_chat, "_chat_timeout_seconds", lambda: 7.0)

    response = request("POST", "/api/chat", json={"message": "Inspect this repository"})

    assert response.status_code == 200
    assert response.json()["reply"] == "Ready."
    assert captured["timeout"] == 7.0


def test_workspace_chat_returns_a_bounded_timeout_response(monkeypatch):
    def slow_reply(*_args, **_kwargs):
        time.sleep(1.05)
        return provider.ProviderResult(reply="Late reply.", runtime="test")

    monkeypatch.setattr(provider, "reply", slow_reply)
    monkeypatch.setattr(first_party_chat, "_chat_timeout_seconds", lambda: 0.01)

    response = request("POST", "/api/chat", json={"message": "Inspect this repository"})

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "amosclaud"
    assert "model runtime did not answer within" in body["reply"]
    assert "No repository action was performed" in body["reply"]


def test_workspace_chat_rejects_overlapping_requests_for_one_session():
    session_id = "busy-session"
    assert first_party_chat._claim_session(session_id) is True
    try:
        response = request(
            "POST",
            "/api/chat",
            json={"message": "Second request", "session_id": session_id},
        )
    finally:
        first_party_chat._release_session(session_id)

    assert response.status_code == 409
    assert "already running for this session" in response.json()["detail"]


def test_chat_timeout_configuration_is_bounded(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_CHAT_TIMEOUT", "999")
    assert first_party_chat._chat_timeout_seconds() == 55.0

    monkeypatch.setenv("AMOSCLAUD_CHAT_TIMEOUT", "invalid")
    assert first_party_chat._chat_timeout_seconds() == 45.0


def test_self_hosted_runtime_is_primary(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", "http://model.internal")
    monkeypatch.setenv("AMOSCLAUD_MODEL", "amosclaud-coder")
    monkeypatch.setenv("AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS", "false")

    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "Ready from Amosclaud."}}]}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        captured["timeout"] = kwargs["timeout"]
        return Response()

    monkeypatch.setattr(provider.httpx, "post", fake_post)

    result = provider.reply(
        [{"role": "user", "content": "Hello"}],
        "System",
        timeout=12.0,
    )

    assert result.reply == "Ready from Amosclaud."
    assert result.runtime == "self-hosted"
    assert captured["url"] == "http://model.internal/v1/chat/completions"
    assert captured["json"]["model"] == "amosclaud-coder"
    assert captured["timeout"].read <= 12.0


def test_native_model_is_attempted_before_opted_in_external_adapter(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_MODEL_ENDPOINT", "http://native-model.internal")
    monkeypatch.setenv("AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "external-key")

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "Native reply."}}]}

    def native_post(url, **_kwargs):
        assert url == "http://native-model.internal/v1/chat/completions"
        return Response()

    monkeypatch.setattr(provider.httpx, "post", native_post)

    result = provider.reply([{"role": "user", "content": "Hello"}], "System")

    assert result.reply == "Native reply."
    assert result.runtime == "self-hosted"


def test_provider_status_requires_owner_key(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "owner-key")
    unauthorized = request("GET", "/api/provider/status")
    assert unauthorized.status_code == 401

    authorized = request(
        "GET",
        "/api/provider/status",
        headers={"X-Amosclaud-Owner-Key": "owner-key"},
    )
    assert authorized.status_code == 200
    assert authorized.json()["provider"] == "amosclaud"


def test_external_adapters_are_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AMOSCLAUD_MODEL_URL", raising=False)
    monkeypatch.delenv("AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "not-used")

    result = provider.reply([{"role": "user", "content": "Hello"}], "System")

    assert result.runtime == "unconfigured"
    assert result.status == "degraded"
