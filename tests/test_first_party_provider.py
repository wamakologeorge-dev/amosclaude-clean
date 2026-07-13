from __future__ import annotations

import asyncio

import httpx

from amoscloud_ai import provider
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
        return Response()

    monkeypatch.setattr(provider.httpx, "post", fake_post)

    result = provider.reply([{"role": "user", "content": "Hello"}], "System")

    assert result.reply == "Ready from Amosclaud."
    assert result.runtime == "self-hosted"
    assert captured["url"] == "http://model.internal/v1/chat/completions"
    assert captured["json"]["model"] == "amosclaud-coder"


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
