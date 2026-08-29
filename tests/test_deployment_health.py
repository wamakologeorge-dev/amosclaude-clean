from __future__ import annotations

import httpx

from amoscloud_ai import deployment_health


def test_deployment_health_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AMOSCLAUD_DEPLOYMENT_HEALTHCHECK_ENABLED", raising=False)
    assert deployment_health.status() == {"enabled": False, "reachable": None, "detail": "disabled"}


def test_deployment_health_uses_explicit_url_without_returning_url(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_DEPLOYMENT_HEALTHCHECK_ENABLED", "true")
    monkeypatch.setenv("AMOSCLAUD_DEPLOYMENT_HEALTH_URL", "https://amosclaud.example/health")
    monkeypatch.setattr(deployment_health.httpx, "get", lambda *args, **kwargs: httpx.Response(200))

    result = deployment_health.status()

    assert result["enabled"] is True
    assert result["reachable"] is True
    assert result["status_code"] == 200
    assert "url" not in result


def test_deployment_health_reports_network_failure_safely(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_DEPLOYMENT_HEALTHCHECK_ENABLED", "true")
    monkeypatch.setenv("AMOSCLAUD_DEPLOYMENT_HEALTH_URL", "https://amosclaud.example/health")
    monkeypatch.setattr(deployment_health.httpx, "get", lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ConnectError("nope")))

    result = deployment_health.status()

    assert result["enabled"] is True
    assert result["reachable"] is False
    assert result["detail"] == "ConnectError"
