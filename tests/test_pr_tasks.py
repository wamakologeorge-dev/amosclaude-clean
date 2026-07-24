"""Contract tests for owner-only concurrent PR-agent tasks."""

from fastapi.testclient import TestClient

from amoscloud_ai.main import create_app


def test_pr_agent_task_requires_owner_key(monkeypatch):
    monkeypatch.delenv("AMOSCLAUD_OWNER_KEY", raising=False)
    client = TestClient(create_app())
    response = client.post("/api/v1/agent/tasks", json={"objective": "Repair the dashboard"})
    assert response.status_code == 503


def test_pr_agent_task_is_accepted_and_can_be_polled(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "private-key")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    client = TestClient(create_app())
    headers = {"X-Amosclaud-Owner-Key": "private-key"}
    response = client.post("/api/v1/agent/tasks", headers=headers, json={"objective": "Repair the dashboard"})
    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] in {"queued", "running", "failed"}
    assert payload["branch"].startswith("amosclaud/agent-")
    status = client.get(f"/api/v1/agent/tasks/{payload['task_id']}", headers=headers)
    assert status.status_code == 200
    assert status.json()["task_id"] == payload["task_id"]


def test_pr_agent_tasks_have_distinct_workspaces(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "private-key")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    client = TestClient(create_app())
    headers = {"X-Amosclaud-Owner-Key": "private-key"}
    first = client.post("/api/v1/agent/tasks", headers=headers, json={"objective": "Check service one"}).json()
    second = client.post("/api/v1/agent/tasks", headers=headers, json={"objective": "Check service two"}).json()
    assert first["task_id"] != second["task_id"]
    assert first["branch"] != second["branch"]
