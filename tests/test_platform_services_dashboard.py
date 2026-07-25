"""Tests for the truthful all-services dashboard and the Task A 405 fix."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from amoscloud_ai.api.routes import (
    auth,
    platform_services as ps,
    repositories,
    storage,
)
from amoscloud_ai.main import create_app

EXPECTED_SERVICE_IDS = {
    "web",
    "database",
    "auth-session",
    "repository-store",
    "issues-service",
    "git-transport",
    "object-storage",
    "amosclaud-provider",
    "model-runtime",
    "model-station-network",
    "external-adapters",
    "github-webhook",
    "issue-command",
    "railway",
    "autonomous-pipeline",
    "cicd",
}


def _bind(tmp_path, monkeypatch):
    database = tmp_path / "auth.db"
    monkeypatch.setattr(auth, "DB_PATH", database)
    monkeypatch.setattr(repositories, "DB_PATH", database)
    monkeypatch.setattr(repositories, "REPOSITORY_ROOT", tmp_path / "repos")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path / "storage")


def _make_session(email: str) -> tuple[str, object]:
    token = f"session-{email}"
    now = datetime.now(timezone.utc)
    with auth._connect() as db:
        cursor = db.execute(
            "INSERT INTO users(name,email,password_hash,provider,is_admin,"
            "created_at) VALUES (?,?,?,'password',0,?)",
            (email.split("@", 1)[0], email, auth._hash_password("pw"),
             now.isoformat()),
        )
        user_id = cursor.lastrowid
        db.execute(
            "INSERT INTO sessions(token_hash,user_id,expires_at,created_at) "
            "VALUES (?,?,?,?)",
            (auth._token_hash(token), user_id,
             (now + timedelta(hours=1)).isoformat(), now.isoformat()),
        )
        db.commit()
        user = db.execute(
            "SELECT * FROM users WHERE id=?", (user_id,)
        ).fetchone()
    return token, user


def _get(path: str, token: str | None = None) -> httpx.Response:
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            if token:
                client.cookies.set(auth.SESSION_COOKIE, token)
            return await client.get(path)

    return asyncio.run(run())


# --------------------------------------------------------------------------
# Task A regression: the GET listing methods must exist (no more HTTP 405).
# --------------------------------------------------------------------------
def test_repository_issue_listing_is_not_method_not_allowed(tmp_path, monkeypatch):
    _bind(tmp_path, monkeypatch)
    token, owner = _make_session("owner@example.com")
    repository = repositories.create_repository(
        repositories.RepositoryCreate(name="proj", visibility="private"), owner
    )
    response = _get(f"/api/v1/repositories/{repository.id}/issues", token)
    assert response.status_code == 200
    assert response.json() == []


def test_repository_pull_request_listing_is_not_method_not_allowed(
    tmp_path, monkeypatch
):
    _bind(tmp_path, monkeypatch)
    token, owner = _make_session("owner@example.com")
    repository = repositories.create_repository(
        repositories.RepositoryCreate(name="proj", visibility="private"), owner
    )
    response = _get(
        f"/api/v1/repositories/{repository.id}/pull-requests", token
    )
    assert response.status_code == 200
    assert response.json() == []


def test_issue_get_and_post_are_registered_with_both_methods():
    methods: dict[str, set[str]] = {}
    for route in create_app().routes:
        path = getattr(route, "path", "")
        if path == "/api/v1/repositories/{repository_id}/issues":
            methods.setdefault(path, set()).update(
                getattr(route, "methods", set()) or set()
            )
    registered = methods.get("/api/v1/repositories/{repository_id}/issues", set())
    assert "GET" in registered
    assert "POST" in registered


# --------------------------------------------------------------------------
# Task B: truthful all-services dashboard endpoint.
# --------------------------------------------------------------------------
def test_endpoint_requires_authenticated_session(tmp_path, monkeypatch):
    _bind(tmp_path, monkeypatch)
    response = _get("/api/v1/platform/services")
    assert response.status_code == 401


def test_every_expected_service_has_an_entry(tmp_path, monkeypatch):
    _bind(tmp_path, monkeypatch)
    token, _ = _make_session("owner@example.com")
    response = _get("/api/v1/platform/services", token)
    assert response.status_code == 200
    payload = response.json()
    ids = {service["id"] for service in payload["services"]}
    assert ids == EXPECTED_SERVICE_IDS
    assert payload["summary"]["total"] == len(EXPECTED_SERVICE_IDS)
    for service in payload["services"]:
        assert service["state"] in ps.STATES
        assert service["explanation"]
        assert service["evidence"]


def test_services_without_a_probe_report_unknown_not_operational():
    services = {entry["id"]: entry for entry in ps._collect()}
    for sid in ("autonomous-pipeline", "cicd"):
        assert services[sid]["state"] == ps.UNKNOWN
        assert services[sid]["state"] != ps.OPERATIONAL
        assert "no " in services[sid]["explanation"].lower()


def test_failing_check_reports_unreachable_with_actionable_message(monkeypatch):
    # git missing is a real, deterministic failure path.
    monkeypatch.setattr(ps.shutil, "which", lambda name: None)
    entry = ps._check_git_transport()
    assert entry["state"] == ps.UNREACHABLE
    assert entry["remediation"]
    assert "errno" not in entry["explanation"].lower()
    assert "errno" not in entry["remediation"].lower()


def test_one_failing_check_never_breaks_the_whole_response(monkeypatch):
    def boom() -> dict:
        raise RuntimeError("simulated failure")

    patched = tuple(
        (sid, name, boom if sid == "database" else check)
        for sid, name, check in ps._CHECKS
    )
    monkeypatch.setattr(ps, "_CHECKS", patched)
    services = {entry["id"]: entry for entry in ps._collect()}
    assert len(services) == len(EXPECTED_SERVICE_IDS)
    assert services["database"]["state"] == ps.UNREACHABLE
    assert "errno" not in services["database"]["remediation"].lower()
    # Every other service still resolved.
    assert services["web"]["state"] == ps.OPERATIONAL


def test_response_never_leaks_secret_values(tmp_path, monkeypatch):
    _bind(tmp_path, monkeypatch)
    monkeypatch.setenv("GITHUB_APP_WEBHOOK_SECRET", "SECRET-WEBHOOK-VALUE")
    monkeypatch.setenv("AMOSCLAUD_API_KEY", "SECRET-API-KEY-VALUE")
    monkeypatch.setenv("OPENAI_API_KEY", "SECRET-OPENAI-VALUE")
    token, _ = _make_session("owner@example.com")
    response = _get("/api/v1/platform/services", token)
    assert response.status_code == 200
    body = response.text
    assert "SECRET-WEBHOOK-VALUE" not in body
    assert "SECRET-API-KEY-VALUE" not in body
    assert "SECRET-OPENAI-VALUE" not in body


def test_command_center_page_renders_the_dashboard_markup(tmp_path, monkeypatch):
    _bind(tmp_path, monkeypatch)
    token, _ = _make_session("owner@example.com")
    response = _get("/cloud/agent", token)
    assert response.status_code == 200
    assert "services-dashboard" in response.text
    assert "services-tiles" in response.text
