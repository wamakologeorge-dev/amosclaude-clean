"""Amosclaud control-bus server router.

This module implements the requested ``Amosclaud.py server.cb`` contract as a
bounded FastAPI control surface. It exposes identity and capability discovery,
provider and bundle summaries, and a small command router without exposing
secrets or permitting arbitrary code execution.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from amoscloud_ai import __version__, provider
from amoscloud_ai.api.routes.auth import get_user_from_session
from amoscloud_ai.api.routes.autonomous_keys import authenticate_autonomous_key
from amoscloud_ai.mapping_bundles import MappingBundleStore

router = APIRouter(prefix="/server/cb/amosclaud", tags=["amosclaud-server-cb"])
store = MappingBundleStore()

SERVER_ID = "amosclaud.server.cb"
SERVER_NAME = "Amosclaud Control Bus"
SUPPORTED_ACTIONS = ("inspect", "list-bundles", "provider-summary", "capabilities")
_SENSITIVE_TERMS = ("key", "token", "secret", "password", "credential", "authorization")


class ControlCommand(BaseModel):
    action: Literal["inspect", "list-bundles", "provider-summary", "capabilities"]
    target: str | None = Field(default=None, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "").strip()
    scheme, separator, value = authorization.partition(" ")
    if separator and scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return None


def _require_actor(request: Request) -> Any:
    actor = get_user_from_session(request.cookies.get("amos_session"))
    if actor:
        return actor
    actor = authenticate_autonomous_key(_bearer_token(request))
    if actor:
        return actor
    raise HTTPException(status_code=401, detail="Amosclaud authentication required")


def _provider_summary() -> dict[str, Any]:
    raw_state = provider.status()
    state = raw_state if isinstance(raw_state, dict) else {}
    raw_network = state.get("model_network", {})
    network = raw_network if isinstance(raw_network, dict) else {}
    return {
        "ready": bool(
            network.get("ready")
            or state.get("self_hosted_configured")
            or state.get("amosclaud_api_configured")
            or state.get("openai_configured")
            or state.get("anthropic_configured")
        ),
        "self_hosted_configured": bool(state.get("self_hosted_configured")),
        "amosclaud_api_configured": bool(state.get("amosclaud_api_configured")),
        "openai_configured": bool(state.get("openai_configured")),
        "anthropic_configured": bool(state.get("anthropic_configured")),
        "model_network_ready": bool(network.get("ready")),
    }


def _redact_metadata(value: Any, key: str = "") -> Any:
    """Redact secret-like values before returning bundle metadata."""
    if any(term in key.lower() for term in _SENSITIVE_TERMS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(item_key): _redact_metadata(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_metadata(item) for item in value]
    return value


def _safe_bundle_list() -> list[dict[str, Any]]:
    bundles: list[dict[str, Any]] = []
    for item in store.list():
        safe_item = dict(item)
        safe_item["metadata"] = _redact_metadata(safe_item.get("metadata", {}))
        bundles.append(safe_item)
    return bundles


def _capabilities() -> dict[str, Any]:
    return {
        "server_id": SERVER_ID,
        "actions": list(SUPPORTED_ACTIONS),
        "resources": [
            "provider-readiness",
            "mapping-bundle-inventory",
            "Amosclaud.bytes metadata",
        ],
        "arbitrary_code_execution": False,
        "secret_values_exposed": False,
        "authentication": ["session", "autonomous-bearer-key"],
    }


@router.get("")
def server_identity(request: Request) -> dict[str, Any]:
    _require_actor(request)
    bundles = _safe_bundle_list()
    return {
        "id": SERVER_ID,
        "name": SERVER_NAME,
        "version": __version__,
        "state": "ready",
        "provider": _provider_summary(),
        "bundles": {
            "count": len(bundles),
            "total_bytes": sum(int(item.get("byte_size", 0)) for item in bundles),
            "format": "Amosclaud.bytes",
        },
        "capabilities": _capabilities(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/capabilities")
def capabilities(request: Request) -> dict[str, Any]:
    _require_actor(request)
    return _capabilities()


@router.post("/command")
def execute_command(command: ControlCommand, request: Request) -> dict[str, Any]:
    _require_actor(request)
    if command.action == "capabilities":
        result: Any = _capabilities()
    elif command.action == "provider-summary":
        result = _provider_summary()
    elif command.action == "list-bundles":
        result = {"bundles": _safe_bundle_list()}
    elif command.action == "inspect":
        if not command.target:
            raise HTTPException(status_code=422, detail="target is required for inspect")
        try:
            manifest = store.read(command.target)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Bundle not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        result = {
            "filename": command.target,
            "schema": manifest.get("schema"),
            "name": manifest.get("name"),
            "version": manifest.get("version"),
            "created_at": manifest.get("created_at"),
            "metadata": _redact_metadata(manifest.get("metadata", {})),
            "mapping_count": len(manifest.get("mappings", {})),
        }
    else:  # pragma: no cover - Literal validation blocks this path.
        raise HTTPException(status_code=422, detail="Unsupported control action")

    return {
        "server_id": SERVER_ID,
        "action": command.action,
        "target": command.target,
        "result": result,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
