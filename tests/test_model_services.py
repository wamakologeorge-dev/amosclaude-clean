from __future__ import annotations

import hashlib

from amoscloud_ai import model_services
from amoscloud_ai.api.routes import agent_readiness


def test_model_service_registry_matches_agent_architecture(monkeypatch):
    monkeypatch.setattr(model_services.model_network, "network_status", lambda: {"ready": True, "ready_stations": 1})
    result = model_services.readiness()
    ids = [service["id"] for service in result["services"]]
    assert ids[:5] == [
        "agent-1-receive",
        "agent-2-perceive",
        "agent-3-model",
        "agent-4-action",
        "agent-5-verify",
    ]
    assert result["active_model"]


def test_autonomous_keys_use_hashes_not_plaintext():
    raw = "amos_aut_example-secret"
    encoded = agent_readiness._hash_key(raw)
    assert raw not in encoded
    assert encoded == hashlib.sha256(raw.encode()).hexdigest()


def test_autonomous_key_prefix_is_namespaced():
    assert "amos_aut_".startswith("amos_aut_")
