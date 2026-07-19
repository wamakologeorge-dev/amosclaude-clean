"""Tests for health, pipelines, and deployments endpoints."""

from __future__ import annotations

import asyncio

import httpx

from amoscloud_ai.main import create_app
from amoscloud_ai.api.routes import agent, deployments

app = create_app()


async def _request(method: str, path: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, **kwargs)


def request(method: str, path: str, **kwargs):
    return asyncio.run(_request(method, path, **kwargs))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def test_root_requires_authentication():
    resp = request("GET", "/")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


def test_login_page_is_served_by_the_application():
    resp = request("GET", "/login")
    assert resp.status_code == 200
    assert "Amosclaud" in resp.text


def test_dashboard_assets_are_served_by_the_application():
    resp = request("GET", "/static/app.js")
    assert resp.status_code == 200
    assert "window.location.origin" in resp.text


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health_ok():
    resp = request("GET", "/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "environment" in data
    assert "timestamp" in data


# ---------------------------------------------------------------------------
# Autonomous runtime
# ---------------------------------------------------------------------------

def test_autonomous_runtime_profile():
    resp = request("GET", "/api/v1/agent")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Amosclaud Autonomous Agent"
    assert data["role"] == "agent assistant and governed autonomous engineering system"
    assert data["mode"] == "agent"
    assert data["scope"] == ["amosclaud.com", "Amosclaud autonomous pipeline"]


def test_autonomous_runtime_requires_authentication():
    payload = {
        "mode": "autonomous-check",
        "objective": "verify server health",
        "branch": "main",
    }
    resp = request("POST", "/api/v1/agent/run", json=payload)
    assert resp.status_code == 401


def test_authenticated_user_can_run_autonomous_runtime(monkeypatch):
    payload = {
        "mode": "autonomous-check",
        "objective": "verify server health",
        "branch": "main",
    }
    monkeypatch.setattr(agent, "get_user_from_session", lambda _token: {"id": 1, "name": "Developer"})
    resp = request(
        "POST",
        "/api/v1/agent/run",
        json=payload,
        cookies={"amos_session": "test-session"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] is True
    assert data["mode"] == "autonomous-check"
    assert data["objective"] == "verify server health"
    assert data["pipeline_id"]
    assert data["status"] in ("pending", "success", "failed")
    assert data["reply"].startswith("Amosclaud Autonomous Runtime:")
    assert data["checks"]
    assert data["logs"]


def test_admin_session_answers_question_without_key_or_pipeline(monkeypatch):
    payload = {
        "mode": "autonomous-check",
        "objective": "What can I build here",
        "branch": "main",
    }
    admin = {"id": 1, "name": "Owner", "is_admin": 1}
    monkeypatch.setattr(agent, "get_user_from_session", lambda _token: admin)

    def reject_key_auth(_token):
        raise AssertionError("A signed-in admin must not be asked for an API key")

    monkeypatch.setattr(agent, "authenticate_autonomous_key", reject_key_auth)
    monkeypatch.setattr(
        agent,
        "dispatch_task",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("A guidance question must not start a pipeline")
        ),
    )

    resp = request(
        "POST",
        "/api/v1/agent/run",
        json=payload,
        cookies={"amos_session": "admin-session"},
        headers={"Authorization": "Bearer should-not-be-used"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["pipeline_id"].startswith("conversation-")
    assert data["checks"] == []
    assert "web application" in data["reply"]


def test_autonomous_runtime_rejects_unknown_mode():
    resp = request("POST", "/api/v1/agent/run", json={"mode": "chat"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Pipelines
# ---------------------------------------------------------------------------

def test_list_pipelines_empty():
    resp = request("GET", "/api/v1/pipelines")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_trigger_pipeline():
    payload = {"trigger": "manual", "branch": "main", "payload": {}}
    resp = request("POST", "/api/v1/pipelines", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["trigger"] == "manual"
    assert data["branch"] == "main"
    assert data["message"]
    assert data["copilot_reply"].startswith("Amosclaud Autonomous Server:")
    assert data["copilot_role"] == "autonomous build, deployment, and monitoring server"
    assert data["delegation_target"] == "Amosclaud autonomous pipeline"
    assert data["jobs"][0]["name"] == "Build"
    assert data["jobs"][0]["logs"]


def test_get_pipeline_not_found():
    resp = request("GET", "/api/v1/pipelines/nonexistent-id")
    assert resp.status_code == 404


def test_cancel_pipeline():
    payload = {"trigger": "push", "branch": "feature/x", "payload": {}}
    create_resp = request("POST", "/api/v1/pipelines", json=payload)
    pipeline_id = create_resp.json()["id"]
    cancel_resp = request("DELETE", f"/api/v1/pipelines/{pipeline_id}")
    assert cancel_resp.status_code in (204, 409)


# ---------------------------------------------------------------------------
# Deployments
# ---------------------------------------------------------------------------

def test_list_deployments_empty():
    resp = request("GET", "/api/v1/deployments")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_start_deployment():
    payload = {"version": "v1.0.0", "environment": "staging"}
    resp = request("POST", "/api/v1/deployments", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["version"] == "v1.0.0"
    assert data["environment"] == "staging"
    assert data["message"]
    assert data["copilot_reply"].startswith("Amosclaud Autonomous Server:")
    assert data["copilot_role"] == "autonomous build, deployment, and monitoring server"
    assert data["delegation_target"] == "Amosclaud autonomous pipeline"


def test_worker_deployment_requires_authenticated_user(monkeypatch):
    payload = {
        "version": "v1.0.0",
        "environment": "staging",
        "repo_url": "https://github.com/example/project.git",
        "start_command": "python app.py",
    }
    denied = request("POST", "/api/v1/deployments", json=payload)
    assert denied.status_code == 401
    monkeypatch.setattr(deployments.auth_routes, "get_user_from_session", lambda token: {"id": 1})
    accepted = request(
        "POST",
        "/api/v1/deployments",
        json=payload,
        cookies={"amos_session": "valid-session"},
    )
    assert accepted.status_code == 201
    assert accepted.json()["status"] == "pending"


def test_get_deployment_not_found():
    resp = request("GET", "/api/v1/deployments/nonexistent-id")
    assert resp.status_code == 404


def test_rollback_deployment():
    create_resp = request("POST", "/api/v1/deployments", json={"version": "v2.0.0", "environment": "production"})
    deployment_id = create_resp.json()["id"]
    resp = request("POST", f"/api/v1/deployments/{deployment_id}/rollback")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rolled_back"


def test_rollback_not_found():
    resp = request("POST", "/api/v1/deployments/nonexistent-id/rollback")
    assert resp.status_code == 404
