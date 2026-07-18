"""Tests for health, pipelines, and deployments endpoints."""

from __future__ import annotations

import asyncio

import httpx

from amoscloud_ai.main import create_app

app = create_app()


async def _request(method: str, path: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, **kwargs)


def request(method: str, path: str, **kwargs):
    return asyncio.run(_request(method, path, **kwargs))


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
# Autonomous Agent
# ---------------------------------------------------------------------------

def test_autonomous_agent_profile():
    resp = request("GET", "/api/v1/agent")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Amosclaud Autonomous Server"
    assert data["role"] == "autonomous build, deployment, and monitoring server"
    assert data["mode"] == "autonomous"
    assert data["scope"] == ["amosclaud.com", "Amosclaud autonomous pipeline"]


def test_autonomous_agent_run():
    payload = {
        "mode": "autonomous-check",
        "objective": "verify server health",
        "branch": "main",
    }
    resp = request("POST", "/api/v1/agent/run", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] is True
    assert data["mode"] == "autonomous-check"
    assert data["objective"] == "verify server health"
    assert data["pipeline_id"]
    assert data["status"] in ("pending", "success", "failed")
    assert data["reply"].startswith("Amosclaud Autonomous Server:")
    assert data["checks"]
    assert data["logs"]


def test_autonomous_agent_rejects_unknown_mode():
    resp = request("POST", "/api/v1/agent/run", json={"mode": "chat"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Pipelines
# ---------------------------------------------------------------------------

def test_list_pipelines_empty():
    resp = request("GET", "/api/v1/pipelines")
    assert resp.status_code == 200
    # May contain items from other tests; just ensure it's a list
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
    # Create one first
    payload = {"trigger": "push", "branch": "feature/x", "payload": {}}
    create_resp = request("POST", "/api/v1/pipelines", json=payload)
    pipeline_id = create_resp.json()["id"]

    # Cancel it – if already finished in stub mode it should 409
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
    payload = {"environment": "development", "version": "1.0.0", "pre_deploy_tests": False}
    resp = request("POST", "/api/v1/deployments", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["environment"] == "development"
    assert data["message"]
    assert data["copilot_reply"].startswith("Amosclaud Autonomous Server:")
    assert data["copilot_role"] == "autonomous build, deployment, and monitoring server"
    assert data["delegation_target"] == "Amosclaud autonomous pipeline"


def test_get_deployment_not_found():
    resp = request("GET", "/api/v1/deployments/nonexistent-id")
    assert resp.status_code == 404


def test_rollback_deployment():
    # Create a deployment first
    payload = {"environment": "staging", "version": "1.0.1"}
    create_resp = request("POST", "/api/v1/deployments", json=payload)
    dep_id = create_resp.json()["id"]

    rollback_resp = request("POST", f"/api/v1/deployments/{dep_id}/rollback")
    assert rollback_resp.status_code == 200
    data = rollback_resp.json()
    assert data["status"] == "rolled_back"


def test_rollback_not_found():
    resp = request("POST", "/api/v1/deployments/nonexistent-id/rollback")
    assert resp.status_code == 404
