from __future__ import annotations

import httpx

from amoscloud_ai import railway_health


def test_railway_health_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AMOSCLAUD_RAILWAY_HEALTHCHECK_ENABLED", raising=False)
    assert railway_health.status() == {"enabled": False, "reachable": None, "detail": "disabled"}


def test_railway_health_uses_public_domain_without_returning_url(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_RAILWAY_HEALTHCHECK_ENABLED", "true")
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "amosclaud.example")
    monkeypatch.setattr(railway_health.httpx, "get", lambda *args, **kwargs: httpx.Response(200))

    result = railway_health.status()

    assert result["enabled"] is True
    assert result["reachable"] is True
    assert result["status_code"] == 200
    assert "url" not in result


def test_railway_health_reports_network_failure_safely(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_RAILWAY_HEALTHCHECK_ENABLED", "true")
    monkeypatch.setenv("AMOSCLAUD_RAILWAY_HEALTH_URL", "https://amosclaud.example/health")
    monkeypatch.setattr(railway_health.httpx, "get", lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ConnectError("nope")))

    result = railway_health.status()

    assert result["enabled"] is True
    assert result["reachable"] is False
    assert result["detail"] == "ConnectError"
