"""Private control-plane client for isolated developer workspaces.

The public Amosclaud web process never receives a Docker socket. It sends a
small, authenticated lifecycle request to a separately deployed workspace
worker. The worker is responsible for container creation and enforcement of
runtime limits.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


class WorkspaceProviderError(RuntimeError):
    """Raised when the private workspace worker cannot complete an operation."""


@dataclass(frozen=True, slots=True)
class WorkspaceProviderConfig:
    base_url: str
    token: str
    timeout_seconds: float

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token)


def _secret_value(name: str) -> str:
    direct = os.getenv(name, "").strip()
    if direct:
        return direct
    path_value = os.getenv(f"{name}_FILE", "").strip()
    if not path_value:
        return ""
    path = Path(path_value)
    try:
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def provider_config() -> WorkspaceProviderConfig:
    return WorkspaceProviderConfig(
        base_url=os.getenv("AMOSCLAUD_WORKSPACE_PROVIDER_URL", "").strip().rstrip("/"),
        token=_secret_value("AMOSCLAUD_WORKSPACE_PROVIDER_TOKEN"),
        timeout_seconds=max(
            1.0,
            min(float(os.getenv("AMOSCLAUD_WORKSPACE_PROVIDER_TIMEOUT", "20")), 60.0),
        ),
    )


def _request(method: str, path: str, *, payload: dict[str, Any] | None = None) -> dict:
    config = provider_config()
    if not config.configured:
        raise WorkspaceProviderError(
            "The isolated workspace provider is not configured. Set "
            "AMOSCLAUD_WORKSPACE_PROVIDER_URL and a workspace provider token."
        )

    try:
        response = httpx.request(
            method,
            f"{config.base_url}{path}",
            json=payload,
            headers={
                "Authorization": f"Bearer {config.token}",
                "Accept": "application/json",
                "User-Agent": "Amosclaud-Workspace-Control/1.0",
            },
            timeout=config.timeout_seconds,
            follow_redirects=False,
        )
    except httpx.HTTPError as exc:
        raise WorkspaceProviderError(
            f"Workspace provider request failed: {type(exc).__name__}"
        ) from exc

    if response.status_code >= 400:
        detail = "Workspace provider rejected the request"
        try:
            body = response.json()
            if isinstance(body, dict) and body.get("detail"):
                detail = str(body["detail"])
        except ValueError:
            pass
        raise WorkspaceProviderError(detail)

    try:
        result = response.json()
    except ValueError as exc:
        raise WorkspaceProviderError("Workspace provider returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise WorkspaceProviderError("Workspace provider returned an invalid response")
    return result


def provision_workspace(payload: dict[str, Any]) -> dict:
    return _request("POST", "/v1/workspaces", payload=payload)


def start_workspace(workspace_id: str) -> dict:
    return _request("POST", f"/v1/workspaces/{workspace_id}/start")


def stop_workspace(workspace_id: str) -> dict:
    return _request("POST", f"/v1/workspaces/{workspace_id}/stop")


def restart_workspace(workspace_id: str) -> dict:
    return _request("POST", f"/v1/workspaces/{workspace_id}/restart")


def delete_workspace(workspace_id: str) -> dict:
    return _request("DELETE", f"/v1/workspaces/{workspace_id}")


def workspace_status(workspace_id: str) -> dict:
    return _request("GET", f"/v1/workspaces/{workspace_id}")
