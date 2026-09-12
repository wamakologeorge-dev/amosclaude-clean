from __future__ import annotations

from amoscloud_ai.mcp_transport_security import (
    DEFAULT_MCP_HOSTS,
    DEFAULT_MCP_ORIGINS,
    public_mcp_transport_security,
)


def test_public_mcp_transport_security_allows_amosclaud_and_chatgpt_hosts(monkeypatch):
    monkeypatch.delenv("AMOSCLAUD_MCP_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("AMOSCLAUD_MCP_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("AMOSCLAUD_PUBLIC_URL", raising=False)

    settings = public_mcp_transport_security()

    assert set(settings.allowed_hosts) == set(DEFAULT_MCP_HOSTS)
    assert set(settings.allowed_origins) == set(DEFAULT_MCP_ORIGINS)
    assert settings.enable_dns_rebinding_protection is True


def test_public_mcp_transport_security_accepts_operator_host(monkeypatch):
    operator_hosts = ("localhost", "host", "host:8443")
    operator_origins = ("https://localhost",)
    monkeypatch.setenv("AMOSCLAUD_PUBLIC_URL", operator_origins[0])
    monkeypatch.setenv("AMOSCLAUD_MCP_ALLOWED_HOSTS", ",".join(operator_hosts[1:]))
    monkeypatch.setenv("AMOSCLAUD_MCP_ALLOWED_ORIGINS", operator_origins[0])

    settings = public_mcp_transport_security()

    assert set(settings.allowed_hosts) == set(DEFAULT_MCP_HOSTS) | set(operator_hosts)
    assert set(settings.allowed_origins) == set(DEFAULT_MCP_ORIGINS) | set(operator_origins)
