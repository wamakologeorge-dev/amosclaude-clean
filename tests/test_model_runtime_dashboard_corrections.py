"""Regression tests for model provider dashboard corrections."""
from __future__ import annotations

import socket

from amoscloud_ai import model_runtime
from amoscloud_ai.api.routes import platform_services as ps


def test_provider_path_is_operational_via_online_station(monkeypatch):
    monkeypatch.setattr(
        ps.model_runtime,
        "network_state",
        lambda: {
            "configured": True,
            "ready": True,
            "ready_stations": 1,
        },
    )
    monkeypatch.setattr(
        ps,
        "_self_hosted_reachable",
        lambda: False,
    )

    entry = ps._check_amosclaud_provider()

    assert entry["state"] == ps.OPERATIONAL
    assert "station" in entry["explanation"].lower()
    assert "1" in entry["explanation"]


def test_tcp_preflight_timeout_names_probe_timeout(monkeypatch):
    monkeypatch.delenv("AMOSCLAUD_MODEL_ENDPOINT", raising=False)
    monkeypatch.delenv("AMOSCLAUD_BOT_URL", raising=False)
    monkeypatch.setenv(
        "AMOSCLAUD_MODEL_URL",
        "http://amosclaud-model.railway.internal:11434",
    )
    model_runtime.reset_cache()
    candidate = next(
        item
        for item in model_runtime.resolve_candidates(
            {"configured": False, "ready": False, "ready_stations": 0}
        )
        if item.key == "self-hosted"
    )
    monkeypatch.setattr(
        model_runtime,
        "_resolve_host",
        lambda host, port: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, port))
        ],
    )

    def timeout(host: str, port: int, budget: float) -> None:
        raise socket.timeout("timed out")

    monkeypatch.setattr(model_runtime, "_tcp_connect", timeout)

    health = model_runtime.candidate_health(candidate, force=True)

    assert health.reachable is False
    assert health.diagnosis is not None
    assert health.diagnosis.code == model_runtime.TIMEOUT
    remediation = health.diagnosis.remediation
    assert "AMOSCLAUD_MODEL_PROBE_TIMEOUT" in remediation
    assert "AMOSCLAUD_MODEL_TIMEOUT" not in remediation
    assert "private-network" in remediation
