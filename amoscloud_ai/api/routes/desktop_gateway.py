"""Discovery metadata for configuring Amosclaud as a third-party gateway.

The metadata is intentionally credential-free.  A Desktop client can discover
the OpenAI-compatible base URL and supported capabilities without receiving a
user key or any server-owned model-provider secret.
"""

from __future__ import annotations

import os

from fastapi import APIRouter

from amoscloud_ai.public_url_policy import (
    DEFAULT_PUBLIC_URL,
    normalize_public_amosclaud_url,
)

router = APIRouter(prefix="/api/v1/desktop", tags=["desktop-gateway"])
discovery_router = APIRouter(tags=["desktop-gateway"])

DEFAULT_MODEL = "amosclaud-agent"


def _public_base_url() -> str:
    configured = (
        os.getenv("AMOSCLAUD_PUBLIC_URL", "").strip()
        or os.getenv("AMOSCLAUD_API_URL", "").strip()
        or DEFAULT_PUBLIC_URL
    )
    return normalize_public_amosclaud_url(configured).rstrip("/")


def provider_manifest() -> dict[str, object]:
    """Return the stable, non-secret Desktop/provider contract."""

    base_url = _public_base_url()
    api_base_url = f"{base_url}/v1"
    configured_model = os.getenv("AMOSCLAUD_DESKTOP_MODEL", DEFAULT_MODEL)
    model = configured_model.strip() or DEFAULT_MODEL
    return {
        "schema_version": 1,
        "provider": {
            "id": "amosclaud",
            "name": "Amosclaud",
            "kind": "third-party-gateway",
            "protocol": "openai-compatible",
        },
        "api": {
            "base_url": api_base_url,
            "models_url": f"{api_base_url}/models",
            "chat_completions_url": f"{api_base_url}/chat/completions",
            "responses_url": f"{api_base_url}/responses",
            "streaming": False,
        },
        "authentication": {
            "type": "bearer",
            "header": "Authorization",
            "format": "Bearer <AMOSCLAUD_API_KEY>",
            "key_prefixes": ["amos_aut_", "amos_live_", "amos_test_"],
        },
        "default_model": model,
        "capabilities": [
            "chat",
            "responses",
            "repository-aware-autonomous-work",
        ],
        "mcp_url": f"{base_url}/mcp/",
        "desktop": {
            "app_id": "com.amosclaud.desktop",
            "setup_command": "Amosclaud --configure",
            "environment": {
                "base_url": "AMOSCLAUD_URL",
                "api_key": "AMOSCLAUD_API_KEY",
                "model": "AMOSCLAUD_MODEL",
            },
        },
    }


@discovery_router.get("/.well-known/amosclaud-provider.json")
def well_known_provider() -> dict[str, object]:
    """Publish provider metadata for clients that support auto-discovery."""

    return provider_manifest()


@router.get("/provider")
def desktop_provider() -> dict[str, object]:
    """Return the same metadata under the authenticated platform namespace.

    The response contains no account information and is safe for a Desktop
    client to use before a user has entered a gateway key.
    """

    return provider_manifest()


__all__ = [
    "DEFAULT_MODEL",
    "desktop_provider",
    "discovery_router",
    "provider_manifest",
    "router",
]
