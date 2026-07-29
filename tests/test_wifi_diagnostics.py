"""Regression tests for the managed Wi-Fi network diagnostics endpoint."""

from __future__ import annotations

import asyncio

from fastapi import HTTPException

from amoscloud_ai.api.routes import wifi


def _run() -> dict:
    return asyncio.run(wifi.network_diagnostics())


def test_network_diagnostics_reports_complete_connection_path(monkeypatch):
    async def fake_routeros_request(method: str, path: str, **kwargs):
        del method, kwargs
        responses = {
            "/rest/system/identity": {"name": "Amosclaud-AP"},
            "/rest/system/resource": {"platform": "MikroTik", "uptime": "1d2h"},
            "/rest/interface/wifi/wifi1": {
                "configuration.ssid": "Amosclaud-Admin",
                "channel.frequency": "5500",
                "disabled": "false",
            },
            "/rest/interface/wifi/registration-table": [
                {"mac-address": "00:00:00:00:00:01"}
            ],
        }
        return responses[path]

    async def fake_resolve(hostname: str, timeout: float):
        assert hostname == "network.example.com"
        assert timeout == 5.0
        return True, 4, ["203.0.113.10"]

    async def fake_http_probe(url: str, timeout: float):
        assert timeout == 5.0
        return {
            "configured": True,
            "reachable": True,
            "status_code": 200,
            "latency_ms": 8,
            "detail": "ok",
        }

    monkeypatch.setattr(wifi, "routeros_request", fake_routeros_request)
    monkeypatch.setattr(wifi, "_resolve_hostname", fake_resolve)
    monkeypatch.setattr(wifi, "_http_probe", fake_http_probe)
    monkeypatch.setattr(
        wifi.model_network,
        "network_status",
        lambda: {"configured": True, "ready": True, "ready_stations": 2},
    )
    monkeypatch.setenv(
        "AMOSCLAUD_NETWORK_SERVICE_HEALTH_URL",
        "https://network.example.com/ready",
    )
    monkeypatch.setenv(
        "AMOSCLAUD_NETWORK_INTERNET_PROBE_URL",
        "https://example.com/health",
    )

    payload = _run()

    assert payload["status"] == "passed"
    assert payload["summary"] == {
        "total": 5,
        "passed": 5,
        "failed": 0,
        "skipped": 0,
    }
    assert [entry["id"] for entry in payload["checks"]] == [
        "local-network",
        "name-resolution",
        "wifi",
        "internet-connectivity",
        "amosclaud-network-service",
    ]
    assert payload["access_point"]["ssid"] == "Amosclaud-Admin"
    assert payload["access_point"]["connected_devices"] == 1
    assert payload["network_service"]["local"]["ready_stations"] == 2


def test_network_diagnostics_surfaces_dns_and_router_failures(monkeypatch):
    async def unavailable_router(*args, **kwargs):
        del args, kwargs
        raise HTTPException(status_code=502, detail="Could not connect to access point")

    async def unresolved(hostname: str, timeout: float):
        del hostname, timeout
        return False, 11, []

    async def unavailable_probe(url: str, timeout: float):
        del url, timeout
        return {
            "configured": True,
            "reachable": False,
            "latency_ms": 12,
            "detail": "ConnectError",
        }

    monkeypatch.setattr(wifi, "routeros_request", unavailable_router)
    monkeypatch.setattr(wifi, "_resolve_hostname", unresolved)
    monkeypatch.setattr(wifi, "_http_probe", unavailable_probe)
    monkeypatch.setattr(
        wifi.model_network,
        "network_status",
        lambda: {"configured": False, "ready_stations": 0},
    )
    monkeypatch.delenv("AMOSCLAUD_NETWORK_SERVICE_HEALTH_URL", raising=False)

    payload = _run()

    states = {entry["id"]: entry["state"] for entry in payload["checks"]}
    assert payload["status"] == "failed"
    assert states["local-network"] == "failed"
    assert states["name-resolution"] == "failed"
    assert states["wifi"] == "failed"
    assert states["internet-connectivity"] == "failed"
    assert states["amosclaud-network-service"] == "skipped"
    assert payload["summary"]["failed"] == 4
