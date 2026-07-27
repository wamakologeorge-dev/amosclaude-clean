"""Server-managed cloud configuration for Amosclaud gateways and sandboxes."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class CloudConfiguration:
    gateway_path: Path
    organization_settings_path: Path
    gateway: dict[str, Any]
    organization_settings: dict[str, Any]

    @property
    def server_managed(self) -> bool:
        return bool(
            self.gateway.get("server_managed")
            and self.organization_settings.get("server_managed")
        )

    @property
    def network_domain_allowlist(self) -> tuple[str, ...]:
        gateway_domains = self.gateway.get("network", {}).get(
            "domain_allowlist",
            [],
        )
        organization_domains = self.organization_settings.get(
            "network_domain_allowlist",
            [],
        )
        return tuple(
            dict.fromkeys(
                str(domain).strip().lower()
                for domain in [*gateway_domains, *organization_domains]
                if str(domain).strip()
            )
        )

    @property
    def default_sandbox_image(self) -> str:
        return str(
            self.organization_settings.get("default_sandbox_image")
            or self.gateway.get("sandbox", {}).get("default_image")
            or ""
        )

    def public_status(self) -> dict[str, Any]:
        sync = self.organization_settings.get("repository_sync", {})
        return {
            "server_managed": self.server_managed,
            "gateway_version": self.gateway.get("version"),
            "organization_settings_version": self.organization_settings.get(
                "version"
            ),
            "network_domain_allowlist": list(self.network_domain_allowlist),
            "default_sandbox_image": self.default_sandbox_image,
            "repository_sync": {
                "direction": sync.get("direction"),
                "github_to_platform": sync.get("github_to_platform"),
                "platform_to_github": sync.get("platform_to_github"),
                "overwrite_dirty_workspaces": bool(
                    sync.get("overwrite_dirty_workspaces")
                ),
                "overwrite_diverged_history": bool(
                    sync.get("overwrite_diverged_history")
                ),
            },
            "configuration_files": {
                "gateway": str(self.gateway_path),
                "organization_settings": str(self.organization_settings_path),
            },
        }


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _gateway_path() -> Path:
    configured = os.getenv("AMOSCLAUD_GATEWAY_CONFIG", "").strip()
    return Path(configured) if configured else _root() / "config" / "gateway.yaml"


def _organization_settings_path() -> Path:
    configured = os.getenv("AMOSCLAUD_ORGANIZATION_SETTINGS", "").strip()
    return (
        Path(configured)
        if configured
        else _root() / "config" / "organization-settings.json"
    )


def _read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Cloud gateway configuration must be an object: {path}")
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(
            f"Organization settings configuration must be an object: {path}"
        )
    return payload


def _validate(configuration: CloudConfiguration) -> CloudConfiguration:
    if configuration.gateway.get("version") != 1:
        raise ValueError("Unsupported Amosclaud gateway configuration version")
    if configuration.organization_settings.get("version") != 1:
        raise ValueError("Unsupported Amosclaud organization settings version")
    if not configuration.server_managed:
        raise ValueError("Cloud configuration must be server managed")
    if not configuration.network_domain_allowlist:
        raise ValueError("Cloud configuration requires a network domain allowlist")
    if not configuration.default_sandbox_image:
        raise ValueError("Cloud configuration requires a default sandbox image")
    return configuration


@lru_cache(maxsize=1)
def load_cloud_configuration() -> CloudConfiguration:
    gateway_path = _gateway_path().expanduser().resolve()
    organization_settings_path = _organization_settings_path().expanduser().resolve()
    configuration = CloudConfiguration(
        gateway_path=gateway_path,
        organization_settings_path=organization_settings_path,
        gateway=_read_yaml(gateway_path),
        organization_settings=_read_json(organization_settings_path),
    )
    return _validate(configuration)


def reset_cloud_configuration_cache() -> None:
    load_cloud_configuration.cache_clear()
