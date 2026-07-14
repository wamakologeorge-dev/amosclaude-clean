from datetime import datetime, timezone

from fastapi.testclient import TestClient

from amoscloud_ai.api.routes import github_travel
from amoscloud_ai.main import create_app
from amoscloud_ai.models import RepositoryTaskResponse, RepositoryTaskStatus


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, **kwargs):
        if url.startswith("https://api.github.com/repos/"):
            return _FakeResponse(200, {"permissions": {"push": True}})
        if url.endswith("/api/tags"):
            return _FakeResponse(200, {"models": [{"name": "qwen2.5-coder:3b"}]})
        return _FakeResponse(404, {})


def _task(status=RepositoryTaskStatus.QUEUED, pull_request_url=None):
    now = datetime.now(timezone.utc)
    return RepositoryTaskResponse(
        task_id="task-123",
        status=status,
        objective="Verify production integration",
        branch="amosclaud/agent-task-123",
        message="Task accepted" if status == RepositoryTaskStatus.QUEUED else "Implementation complete",
        created_at=now,
        updated_at=now,
        pull_request_url=pull_request_url,
        logs=["clone", "edit", "test", "push", "pull-request"],
    )


def test_preflight_confirms_github_and_model(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "owner-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "github-secret")
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", "http://amosclaud-model.railway.internal:11434")
    monkeypatch.setattr(github_travel.httpx, "AsyncClient", _FakeAsyncClient)

    with TestClient(create_app()) as client:
        response = client.get(
            "/api/v1/agent/github/preflight",
            headers={"X-Amosclaud-Owner-Key": "owner-secret"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["github"]["reachable"] is True
    assert body["model"]["reachable"] is True
    assert "1 installed model" in body["model"]["detail"]


def test_travel_route_queues_and_reports_completed_pull_request(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "owner-secret")
    monkeypatch.setattr(github_travel, "queue_task", lambda request: _task())
    monkeypatch.setattr(
        github_travel,
        "get_task_status",
        lambda task_id: _task(
            RepositoryTaskStatus.COMPLETED,
            "https://github.com/wamakologeorge-dev/amosclaude-clean/pull/999",
        ),
    )

    with TestClient(create_app()) as client:
        start = client.post(
            "/api/v1/agent/github/travel",
            headers={"X-Amosclaud-Owner-Key": "owner-secret"},
            json={
                "repository": "wamakologeorge-dev/amosclaude-clean",
                "objective": "Verify the full GitHub travel cycle",
                "base_branch": "main",
                "action": "work-and-open-pr",
            },
        )
        status = client.get(
            "/api/v1/agent/github/travel/task-123",
            headers={"X-Amosclaud-Owner-Key": "owner-secret"},
        )

    assert start.status_code == 202
    start_body = start.json()
    assert start_body["accepted"] is True
    assert start_body["branch"].startswith("amosclaud/agent-")
    assert start_body["status_url"].endswith("/task-123")

    assert status.status_code == 200
    status_body = status.json()
    assert status_body["status"] == "completed"
    assert status_body["pull_request_url"].endswith("/pull/999")
    assert status_body["logs"] == ["clone", "edit", "test", "push", "pull-request"]


def test_preflight_never_exposes_secret_values(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "owner-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "super-sensitive-github-token")
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", "http://amosclaud-model.railway.internal:11434")
    monkeypatch.setattr(github_travel.httpx, "AsyncClient", _FakeAsyncClient)

    with TestClient(create_app()) as client:
        response = client.get(
            "/api/v1/agent/github/preflight",
            headers={"X-Amosclaud-Owner-Key": "owner-secret"},
        )

    rendered = response.text
    assert "super-sensitive-github-token" not in rendered
    assert "owner-secret" not in rendered
