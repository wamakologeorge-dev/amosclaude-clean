from __future__ import annotations

import asyncio

import httpx

from amoscloud_ai import provider
from amoscloud_ai.main import create_app


def request(app, method: str, path: str):
    async def _request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path)

    return asyncio.run(_request())


def test_agent_readiness_requires_real_model_probe(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("AMOSCLAUD_CORE_DB", str(tmp_path / "core.db"))
    monkeypatch.setenv("AMOSCLAUD_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setattr(
        provider,
        "probe",
        lambda: {
            "ready": True,
            "provider": "amosclaud",
            "runtime": "self-hosted",
            "model": "test-model",
            "detail": "AMOSCLAUD_AGENT_READY",
        },
    )

    response = request(create_app(), "GET", "/api/v1/agent/readiness")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is True
    assert payload["status"] == "ready"
    assert payload["checks"]["workspace"]["ready"] is True
    assert payload["checks"]["token_authority"]["ready"] is True
    assert payload["checks"]["model"]["detail"] == "AMOSCLAUD_AGENT_READY"


def test_agent_readiness_stays_starting_when_model_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("AMOSCLAUD_CORE_DB", str(tmp_path / "core.db"))
    monkeypatch.setenv("AMOSCLAUD_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setattr(
        provider,
        "probe",
        lambda: {
            "ready": False,
            "provider": "amosclaud",
            "runtime": "self-hosted",
            "model": "test-model",
            "detail": "connection refused",
        },
    )

    response = request(create_app(), "GET", "/api/v1/agent/readiness")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is False
    assert payload["status"] == "starting"
    assert payload["checks"]["model"]["ready"] is False
