"""Safe Streamable HTTP transport settings for public Amosclaud MCP endpoints."""

from __future__ import annotations

import os
from urllib.parse import urlparse

from mcp.server.transport_security import TransportSecuritySettings


DEFAULT_MCP_HOSTS = (
    "amosclauds.com",
    "amosclauds.com:443",
    "www.amosclaud.com",
    "www.amosclaud.com:443",
)
DEFAULT_MCP_ORIGINS = (
    "https://amosclauds.com",
    "https://www.amosclaud.com",
    "https://chatgpt.com",
    "https://chat.openai.com",
)


def _csv_env(name: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


def _public_host() -> str | None:
    raw = os.getenv("AMOSCLAUD_PUBLIC_URL", "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    except ValueError:
        return None
    return parsed.netloc or None


def public_mcp_transport_security() -> TransportSecuritySettings:
    """Return fail-closed host/origin rules for deployed Amosclaud MCP servers.

    The MCP SDK deliberately rejects external Host headers unless a deployment
    supplies an explicit allowlist. Keep the production defaults narrow and let
    operators add an additional public hostname through environment variables.
    """

    hosts = list(DEFAULT_MCP_HOSTS)
    public_host = _public_host()
    if public_host and public_host not in hosts:
        hosts.append(public_host)

    hosts.extend(item for item in _csv_env("AMOSCLAUD_MCP_ALLOWED_HOSTS") if item not in hosts)

    origins = list(DEFAULT_MCP_ORIGINS)
    origins.extend(item for item in _csv_env("AMOSCLAUD_MCP_ALLOWED_ORIGINS") if item not in origins)

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )
