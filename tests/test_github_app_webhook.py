"""Tests for the GitHub App webhook receiver and event feed."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json

import httpx
import pytest

from amoscloud_ai import codex_memory
from amoscloud_ai.api.routes import github_app
from amoscloud_ai.main import create_app

app = create_app()

SECRET = "test-webhook-secret"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_CODEX_MEMORY_DIR", str(tmp_path / "codex"))
    monkeypatch.setenv("AMOSCLAUD_GITHUB_EVENTS_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("GITHUB_APP_WEBHOOK_SECRET", SECRET)
    codex_memory.reset_cache_for_tests()
    yield
    codex_memory.reset_cache_for_tests()


def request(method: str, path: str, **kwargs):
    async def _go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(_go())


def deliver(event: str, payload: dict, *, secret: str | None = SECRET, signature: str | None = None):
    body = json.dumps(payload).encode()
    headers = {
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": "d3l1v3ry-1234",
        "Content-Type": "application/json",
    }
    if signature is not None:
        headers["X-Hub-Signature-256"] = signature
    elif secret is not None:
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Hub-Signature-256"] = f"sha256={digest}"
    return request("POST", "/api/v1/agent/github/webhook", content=body, headers=headers)


def test_ping_is_answered():
    response = deliver("ping", {"zen": "Keep it logically awesome."})
    assert response.status_code == 200
    assert response.json()["pong"] == "Keep it logically awesome."


def test_bad_signature_is_rejected():
    response = deliver("push", {"repository": {"full_name": "a/b"}}, signature="sha256=bad")
    assert response.status_code == 401
    assert deliver("push", {}, secret=None).status_code == 401


def test_push_event_is_recorded_in_feed_and_codex(monkeypatch):
    payload = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "wamakologeorge-dev/amosclaude-clean"},
        "pusher": {"name": "wamakologeorge-dev"},
        "sender": {"login": "wamakologeorge-dev"},
        "commits": [{"id": "abc"}, {"id": "def"}],
        "head_commit": {"message": "Fix repair engine scope"},
    }
    response = deliver("push", payload)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["handled"] is True

    monkeypatch.setattr(
        github_app, "_authenticated_user", lambda _request: {"id": 1, "name": "Owner"}
    )
    feed = request("GET", "/api/v1/agent/github/events")
    assert feed.status_code == 200
    events = feed.json()["events"]
    assert events and events[0]["event"] == "push"
    assert events[0]["repository"] == "wamakologeorge-dev/amosclaude-clean"
    assert "2 commit(s)" in events[0]["summary"]

    hits = codex_memory.search(
        "repair engine scope push", scope="wamakologeorge-dev/amosclaude-clean"
    )
    assert hits and hits[0]["kind"] == "event"


def test_pull_request_merge_summary():
    payload = {
        "action": "closed",
        "number": 557,
        "repository": {"full_name": "wamakologeorge-dev/amosclaude-clean"},
        "sender": {"login": "wamakologeorge-dev"},
        "pull_request": {
            "number": 557,
            "title": "Fix Pre-CI Guardian false failures",
            "merged": True,
            "user": {"login": "wamakologeorge-dev"},
            "changed_files": 3,
            "additions": 40,
            "deletions": 5,
        },
    }
    response = deliver("pull_request", payload)
    assert response.status_code == 200
    hits = codex_memory.search(
        "Pre-CI Guardian merged", scope="wamakologeorge-dev/amosclaude-clean"
    )
    assert hits and "merged" in hits[0]["title"]


def test_events_and_status_require_authentication():
    assert request("GET", "/api/v1/agent/github/events").status_code == 401
    assert request("GET", "/api/v1/agent/github/app").status_code == 401


def test_app_status_reports_configuration(monkeypatch):
    monkeypatch.setattr(
        github_app, "_authenticated_user", lambda _request: {"id": 1, "name": "Owner"}
    )
    deliver("issues", {
        "action": "opened",
        "repository": {"full_name": "wamakologeorge-dev/amosclaude-clean"},
        "issue": {"number": 9, "title": "Bug"},
    })
    response = request("GET", "/api/v1/agent/github/app")
    assert response.status_code == 200
    body = response.json()
    assert body["webhook_secret_configured"] is True
    assert body["events_recorded"] >= 1
    assert body["webhook_path"] == "/api/v1/agent/github/webhook"
