from __future__ import annotations

import base64
import hashlib

import pytest
from fastapi import HTTPException

from amoscloud_ai.connectors.amosclaud_account import oauth
from amoscloud_ai.connectors.amosclaud_account.gateway import (
    ConnectorGatewayError,
    normalize_platform_path,
    required_scope,
)


def test_connector_uses_unique_account_paths(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_PUBLIC_URL", "https://www.amosclaud.com")

    assert oauth.OAUTH_PATH == "/connectors/amosclaud/v1/oauth"
    assert oauth.MCP_PATH == "/connectors/amosclaud/v1/mcp"
    assert oauth.oauth_issuer_url().endswith(oauth.OAUTH_PATH)
    assert oauth.connector_resource_url().endswith(oauth.MCP_PATH)
    assert oauth.authorization_server_metadata_path().endswith(oauth.OAUTH_PATH)
    assert oauth.protected_resource_metadata_path().endswith(oauth.MCP_PATH)


def test_oauth_redirects_require_https_or_localhost():
    assert oauth._valid_redirect_uri("https://chatgpt.com/connector/callback") == (
        "https://chatgpt.com/connector/callback"
    )
    assert oauth._valid_redirect_uri("http://127.0.0.1:9876/callback") == (
        "http://127.0.0.1:9876/callback"
    )

    with pytest.raises(HTTPException):
        oauth._valid_redirect_uri("http://example.com/callback")
    with pytest.raises(HTTPException):
        oauth._valid_redirect_uri("https://example.com/callback#fragment")
    with pytest.raises(HTTPException):
        oauth._valid_redirect_uri("https:///missing-host")
    with pytest.raises(HTTPException):
        oauth._valid_redirect_uri("https://user:password@example.com/callback")


def test_pkce_s256_verification():
    verifier = "a" * 64
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )

    assert oauth._pkce_matches(verifier, challenge) is True
    assert oauth._pkce_matches(verifier + "x", challenge) is False
    assert oauth._pkce_matches("short", challenge) is False
    assert oauth._pkce_matches("é" * 64, challenge) is False


def test_default_scopes_are_full_for_admin_and_bounded_for_members():
    assert "admin:write" in oauth._requested_scopes(None, is_admin=True)
    assert "admin:write" not in oauth._requested_scopes(None, is_admin=False)
    with pytest.raises(HTTPException):
        oauth._requested_scopes("admin:write", is_admin=False)


def test_connector_gateway_supports_full_read_and_write_routes():
    assert normalize_platform_path("/api/v1/repositories", write=False) == ("/api/v1/repositories")
    assert normalize_platform_path("api/v1/tasks", write=True) == "/api/v1/tasks"
    assert required_scope("GET", "/api/v1/repositories") == "repositories:read"
    assert required_scope("POST", "/api/v1/repositories") == "repositories:write"
    assert required_scope("POST", "/api/v1/agent/run") == "tasks:write"
    assert required_scope("POST", "/api/v1/deployments") == "deployments:write"
    assert required_scope("DELETE", "/api/v1/admin/users/12") == "admin:write"


def test_connector_gateway_blocks_external_and_recursive_paths():
    with pytest.raises(ConnectorGatewayError):
        normalize_platform_path("https://example.com/api", write=False)
    with pytest.raises(ConnectorGatewayError):
        normalize_platform_path("/connectors/amosclaud/v1/oauth/token", write=True)
    with pytest.raises(ConnectorGatewayError):
        normalize_platform_path("/health", write=True)


def test_connected_application_mounts_connector_before_platform():
    from amoscloud_ai.connected_app import app

    paths = [getattr(route, "path", "") for route in app.routes]
    assert "/connectors/amosclaud/v1/mcp" in paths
    assert "" in paths
    assert paths.index("/connectors/amosclaud/v1/mcp") < paths.index("")
