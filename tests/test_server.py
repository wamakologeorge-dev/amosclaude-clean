"""Tests for health, pipelines, and deployments endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from amoscloud_ai.main import create_app

app = create_app()
client = TestClient(app)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "environment" in data
    assert "timestamp" in data


# ---------------------------------------------------------------------------
# Pipelines
# ---------------------------------------------------------------------------

def test_list_pipelines_empty():
    resp = client.get("/api/v1/pipelines")
    assert resp.status_code == 200
    # May contain items from other tests; just ensure it's a list
    assert isinstance(resp.json(), list)


def test_trigger_pipeline():
    payload = {"trigger": "manual", "branch": "main", "payload": {}}
    resp = client.post("/api/v1/pipelines", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["trigger"] == "manual"
    assert data["branch"] == "main"


def test_get_pipeline_not_found():
    resp = client.get("/api/v1/pipelines/nonexistent-id")
    assert resp.status_code == 404


def test_cancel_pipeline():
    # Create one first
    payload = {"trigger": "push", "branch": "feature/x", "payload": {}}
    create_resp = client.post("/api/v1/pipelines", json=payload)
    pipeline_id = create_resp.json()["id"]

    # Cancel it – if already finished in stub mode it should 409
    cancel_resp = client.delete(f"/api/v1/pipelines/{pipeline_id}")
    assert cancel_resp.status_code in (204, 409)


# ---------------------------------------------------------------------------
# Deployments
# ---------------------------------------------------------------------------

def test_list_deployments_empty():
    resp = client.get("/api/v1/deployments")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_start_deployment():
    payload = {"environment": "development", "version": "1.0.0", "pre_deploy_tests": False}
    resp = client.post("/api/v1/deployments", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["environment"] == "development"


def test_get_deployment_not_found():
    resp = client.get("/api/v1/deployments/nonexistent-id")
    assert resp.status_code == 404


def test_rollback_deployment():
    # Create a deployment first
    payload = {"environment": "staging", "version": "1.0.1"}
    create_resp = client.post("/api/v1/deployments", json=payload)
    dep_id = create_resp.json()["id"]

    rollback_resp = client.post(f"/api/v1/deployments/{dep_id}/rollback")
    assert rollback_resp.status_code == 200
    data = rollback_resp.json()
    assert data["status"] == "rolled_back"


def test_rollback_not_found():
    resp = client.post("/api/v1/deployments/nonexistent-id/rollback")
    assert resp.status_code == 404
