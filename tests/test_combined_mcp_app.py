from __future__ import annotations

from amoscloud_ai import combined_app


def test_mcp_bearer_authorization_uses_exact_token():
    headers = [(b"authorization", b"Bearer correct-secret")]

    assert combined_app.mcp_request_is_authorized(headers, "correct-secret") is True
    assert combined_app.mcp_request_is_authorized(headers, "wrong-secret") is False
    assert combined_app.mcp_request_is_authorized([], "correct-secret") is False
    assert combined_app.mcp_request_is_authorized(headers, None) is False


def test_mcp_access_key_prefers_dedicated_key(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_AUTONOMOUS_KEY", "autonomous-key")
    monkeypatch.setenv("AMOSCLAUD_MCP_ACCESS_KEY", "mcp-key")

    assert combined_app.expected_mcp_access_key() == "mcp-key"


def test_combined_application_mounts_mcp_before_platform():
    mounts = [route.path for route in combined_app.app.routes if hasattr(route, "path")]

    assert "/mcp" in mounts
    assert "" in mounts
    assert mounts.index("/mcp") < mounts.index("")


def test_combined_platform_registers_vscode_terminal_routes():
    paths = {
        getattr(route, "path", "")
        for route in combined_app.platform_app.routes
    }

    assert "/api/v1/vscode-terminal/repositories" in paths
    assert "/api/v1/vscode-terminal/repositories/{repository_id}/start" in paths
    assert "/api/v1/vscode-terminal/repositories/{repository_id}/ticket" in paths
    assert (
        "/api/v1/vscode-terminal/repositories/{repository_id}/terminal/{terminal_id}"
        in paths
    )


def test_browser_editor_origins_are_explicitly_allowed():
    assert "https://vscode.dev" in combined_app.EDITOR_ORIGINS
    assert "https://insiders.vscode.dev" in combined_app.EDITOR_ORIGINS
    assert "https://github.dev" in combined_app.EDITOR_ORIGINS
