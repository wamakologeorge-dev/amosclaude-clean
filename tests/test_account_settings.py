"""Tests for the account settings/domain-verification tools."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from amoscloud_ai.api.routes import account
from amoscloud_ai.main import create_app

app = create_app()


def request(method: str, path: str, **kwargs):
    async def _go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(_go())


@pytest.fixture
def as_admin(monkeypatch):
    monkeypatch.setattr(
        account,
        "get_user_from_session",
        lambda _session: {"id": 1, "email": "wamakologeorge@gmail.com", "is_admin": True},
    )


def test_settings_requires_authentication():
    assert request("GET", "/api/v1/account/settings").status_code == 401
    assert request("GET", "/api/v1/account/domains").status_code == 401


def test_settings_reports_tool_availability(as_admin, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "Iv1.x")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "shhh")
    response = request("GET", "/api/v1/account/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["billing"] == {"available": True, "href": "/plans"}
    assert body["api_keys"]["href"] == "/admin/service-keys"
    assert body["github_connection"]["available"] is True
    assert body["is_admin"] is True


def test_settings_reflects_missing_services(as_admin, monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    response = request("GET", "/api/v1/account/settings")
    body = response.json()
    assert body["billing"]["available"] is False
    assert body["github_connection"]["available"] is False


def test_domains_reports_configured_hosts(as_admin, monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", '["www.amosclaud.com", "amosclaud.com", "localhost"]')
    response = request(
        "GET",
        "/api/v1/account/domains",
        headers={"host": "www.amosclaud.com", "x-forwarded-proto": "https"},
    )
    assert response.status_code == 200
    body = response.json()
    domains = {d["domain"]: d for d in body["domains"]}
    assert set(domains) == {"www.amosclaud.com", "amosclaud.com"}
    assert domains["www.amosclaud.com"]["active"] is True
    assert domains["www.amosclaud.com"]["https"] is True
    assert domains["amosclaud.com"]["active"] is False


def test_domains_tolerates_comma_separated_hosts(as_admin, monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", "www.amosclaud.com, amosclaud.com")
    response = request("GET", "/api/v1/account/domains")
    body = response.json()
    assert [d["domain"] for d in body["domains"]] == ["www.amosclaud.com", "amosclaud.com"]


def test_domains_normalises_scheme_port_and_duplicates(as_admin, monkeypatch):
    monkeypatch.setenv(
        "ALLOWED_HOSTS",
        '["https://www.amosclaud.com", "https://amosclaud.com", '
        '"http://www.amosclaud.com", "http://localhost", "http://localhost:8000", '
        '"www.amosclaud.com"]',
    )
    response = request("GET", "/api/v1/account/domains")
    body = response.json()
    assert [d["domain"] for d in body["domains"]] == ["www.amosclaud.com", "amosclaud.com"]
