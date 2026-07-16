from amoscloud_ai.main import create_app
from amoscloud_ai.server.cb.Amosclaud import (
    SERVER_ID,
    SUPPORTED_ACTIONS,
    _capabilities,
    _provider_summary,
    _redact_metadata,
)


def test_server_cb_capabilities_are_bounded():
    capabilities = _capabilities()
    assert capabilities["server_id"] == SERVER_ID
    assert capabilities["arbitrary_code_execution"] is False
    assert capabilities["secret_values_exposed"] is False
    assert set(capabilities["actions"]) == set(SUPPORTED_ACTIONS)


def test_server_cb_routes_are_registered():
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/api/v1/server/cb/amosclaud" in paths
    assert "/api/v1/server/cb/amosclaud/capabilities" in paths
    assert "/api/v1/server/cb/amosclaud/command" in paths


def test_metadata_redacts_nested_secret_values():
    metadata = {
        "purpose": "routing",
        "api_key": "private",
        "nested": {"access_token": "private", "region": "us"},
    }
    assert _redact_metadata(metadata) == {
        "purpose": "routing",
        "api_key": "[REDACTED]",
        "nested": {"access_token": "[REDACTED]", "region": "us"},
    }


def test_provider_summary_tolerates_invalid_provider_state(monkeypatch):
    monkeypatch.setattr("amoscloud_ai.server.cb.Amosclaud.provider.status", lambda: None)
    assert _provider_summary() == {
        "ready": False,
        "self_hosted_configured": False,
        "amosclaud_api_configured": False,
        "openai_configured": False,
        "anthropic_configured": False,
        "model_network_ready": False,
    }
