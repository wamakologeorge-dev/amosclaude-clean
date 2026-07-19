"""Contract tests for autonomous API intake and readiness behavior."""

from __future__ import annotations

import asyncio

import httpx

from amoscloud_ai.api.routes import agent, health
from amoscloud_ai.main import create_app

app = create_app()


async def _request(method: str, path: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, **kwargs)


def request(method: str, path: str, **kwargs):
    return asyncio.run(_request(method, path, **kwargs))


def test_liveness_is_fast_and_dependency_independent():
    response = request("GET", "/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_exposes_routes_without_secrets(monkeypatch):
    monkeypatch.setattr(
        health.provider,
        "status",
        lambda: {
            "provider": "amosclaud",
            "self_hosted_configured": False,
            "amosclaud_api_configured": False,
            "external_adapters_enabled": False,
            "openai_configured": False,
            "anthropic_configured": False,
            "model_network": {"ready": False, "ready_stations": 0},
        },
    )
    response = request("GET", "/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["web"]["ready"] is True
    assert body["autonomous_api"]["route"] == "/api/v1/agent/run"
    assert "key" not in str(body).lower().replace("autonomous-key", "")


def test_autonomous_route_rejects_missing_authentication():
    response = request(
        "POST",
        "/api/v1/agent/run",
        json={"mode": "build", "objective": "inspect and verify the server"},
    )
    assert response.status_code == 401


def test_autonomous_bearer_key_is_accepted(monkeypatch):
    monkeypatch.setattr(
        agent,
        "authenticate_autonomous_key",
        lambda token: {"id": 1, "name": "Automation"} if token == "valid-test-key" else None,
    )
    monkeypatch.setattr(agent, "dispatch_task", lambda *_args, **_kwargs: None)
    response = request(
        "POST",
        "/api/v1/agent/run",
        headers={"Authorization": "Bearer valid-test-key"},
        json={"mode": "build", "objective": "inspect, plan, and verify the server"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["status"] == "pending"
    assert body["pipeline_id"]
    assert body["objective"] == "inspect, plan, and verify the server"


def test_build_metadata_enables_plan_first_agent():
    execution_mode, metadata = agent._agent_metadata("build", {})
    assert execution_mode == "build"
    assert metadata["use_agent"] is True
    assert metadata["apply_changes"] is False
    assert metadata["phases"] == ["understand", "inspect", "plan", "act", "verify", "report"]


def test_fix_metadata_authorizes_changes_after_planning():
    execution_mode, metadata = agent._agent_metadata("fix", {})
    assert execution_mode == "build"
    assert metadata["use_agent"] is True
    assert metadata["apply_changes"] is True
