"""Contract tests for the Autonomous Codex configuration layer."""
from __future__ import annotations

import asyncio

import httpx

from amoscloud_ai.api.routes import autonomous_codex, health
from amoscloud_ai.autonomous_codex_config import (
    get_autonomous_codex_configuration,
    select_skill,
)
from amoscloud_ai.main import create_app

app = create_app()


async def _request(method: str, path: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, **kwargs)


def request(method: str, path: str, **kwargs):
    return asyncio.run(_request(method, path, **kwargs))


def test_configuration_has_two_real_skills_and_bounded_limits():
    config = get_autonomous_codex_configuration()
    assert {skill.name for skill in config.skills} == {"engineering", "research-operations"}
    assert config.planning_required is True
    assert config.verification_required is True
    assert 1 <= config.max_iterations <= 25
    assert 1 <= config.max_changed_files <= 50
    assert 5 <= config.max_tool_calls <= 200


def test_write_tools_are_explicitly_classified():
    config = get_autonomous_codex_configuration()
    tools = {tool.name: tool for tool in config.tools}
    assert tools["repository.write"].write_capable is True
    assert tools["repository.write"].approval_required is True
    assert tools["repository.read"].write_capable is False
    assert tools["tests.run"].write_capable is False


def test_skill_selection_routes_engineering_and_operations_objectives():
    assert select_skill("Fix the Python server and run tests").name == "engineering"
    assert select_skill("Investigate why Railway health is degraded").name == "research-operations"
    assert select_skill("anything", "engineering").name == "engineering"


def test_configuration_api_requires_authentication():
    response = request("GET", "/api/v1/autonomous-codex/configuration")
    assert response.status_code == 401


def test_authenticated_configuration_api_is_safe(monkeypatch):
    monkeypatch.setattr(autonomous_codex, "_authenticated_user", lambda _request: {"id": 1, "name": "Owner"})
    response = request("GET", "/api/v1/autonomous-codex/configuration")
    assert response.status_code == 200
    data = response.json()
    assert len(data["skills"]) == 2
    assert data["planning_required"] is True
    assert "provider" in data
    text = response.text.lower()
    assert "api_key" not in text
    assert "token" not in text
    assert "http://" not in text
    assert "https://" not in text


def test_skill_resolver_returns_phases_and_tools(monkeypatch):
    monkeypatch.setattr(autonomous_codex, "_authenticated_user", lambda _request: {"id": 1, "name": "Owner"})
    response = request(
        "POST",
        "/api/v1/autonomous-codex/select-skill",
        json={"objective": "inspect the outage and explain why the model server is unavailable"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["skill"] == "research-operations"
    assert data["phases"][0] == "receive"
    assert "health.inspect" in data["tools"]


def test_dashboard_requires_browser_session(monkeypatch):
    monkeypatch.setattr(health, "get_user_from_session", lambda _token: None)
    response = request("GET", "/autonomous-codex-configuration")
    assert response.status_code == 302
    assert response.headers["location"] == "/login"
