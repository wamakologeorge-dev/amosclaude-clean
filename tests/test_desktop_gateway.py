from __future__ import annotations

from amoscloud_ai.api.routes.desktop_gateway import provider_manifest
from amoscloud_ai.main import create_app
from amoscloud_ai.route_discovery import route_paths


def test_desktop_provider_discovery_routes_are_registered() -> None:
    paths = route_paths(create_app().routes)
    assert "/.well-known/amosclaud-provider.json" in paths
    assert "/api/v1/desktop/provider" in paths


def test_desktop_provider_manifest_is_credential_free(monkeypatch) -> None:
    monkeypatch.setenv("AMOSCLAUD_PUBLIC_URL", "https://www.amosclaud.com/")
    manifest = provider_manifest()

    assert manifest["provider"] == {
        "id": "amosclaud",
        "name": "Amosclaud",
        "kind": "third-party-gateway",
        "protocol": "openai-compatible",
    }
    assert manifest["api"]["base_url"] == "https://www.amosclaud.com/v1"
    models_url = manifest["api"]["models_url"]
    assert models_url == "https://www.amosclaud.com/v1/models"
    assert manifest["default_model"] == "amosclaud-agent"
    assert manifest["authentication"]["type"] == "bearer"
    assert "amos_aut_real_secret" not in str(manifest)
    assert "key_value" not in str(manifest).lower()
