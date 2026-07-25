"""Environment driven configuration for the Amosclaud Model Station agent."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, replace
from typing import Mapping

DEFAULT_URL = "https://www.amosclaud.com"
DEFAULT_BACKEND = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5-coder:1.5b"
INFERENCE_CAPABILITY = "model.inference"

# amoscloud_ai.model_network.ONLINE_WINDOW: a station is only eligible for
# inference while it has been seen within the last 90 seconds.
ONLINE_WINDOW_SECONDS = 90.0


class ConfigError(RuntimeError):
    """Raised when the environment does not describe a usable station."""


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def _text(env: Mapping[str, str], name: str, default: str = "") -> str:
    return str(env.get(name, default) or default).strip()


def _number(
    env: Mapping[str, str], name: str, default: float, minimum: float, maximum: float
) -> float:
    raw = _text(env, name)
    if not raw:
        return _clamp(default, minimum, maximum)
    try:
        return _clamp(float(raw), minimum, maximum)
    except ValueError as error:
        raise ConfigError(f"{name} must be a number, received {raw!r}") from error


def _url(env: Mapping[str, str], name: str, default: str) -> str:
    value = _text(env, name, default).rstrip("/")
    if not value.startswith(("http://", "https://")):
        raise ConfigError(f"{name} must start with http:// or https://, received {value!r}")
    return value


def _required(env: Mapping[str, str], name: str, hint: str) -> str:
    value = _text(env, name)
    if not value:
        raise ConfigError(f"{name} is required. {hint}")
    return value


def _list(env: Mapping[str, str], name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = _text(env, name)
    if not raw:
        return default
    values = tuple(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))
    return values or default


def default_station_name() -> str:
    try:
        host = socket.gethostname().strip()
    except OSError:  # pragma: no cover - hostname lookup practically never fails
        host = ""
    return f"{host or 'local'} model station"[:120]


@dataclass(frozen=True)
class StationConfig:
    """Everything the agent needs to talk to Amosclaud and to its backend."""

    station_id: str
    station_token: str
    base_url: str = DEFAULT_URL
    backend_url: str = DEFAULT_BACKEND
    model: str = DEFAULT_MODEL
    name: str = "model station"
    capabilities: tuple[str, ...] = (INFERENCE_CAPABILITY,)
    poll_interval: float = 2.0
    poll_max_interval: float = 15.0
    heartbeat_interval: float = 30.0
    http_timeout: float = 15.0
    probe_timeout: float = 10.0
    inference_timeout: float = 120.0
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "StationConfig":
        env = os.environ if env is None else env
        config = cls(
            station_id=_required(
                env,
                "AMOSCLAUD_STATION_ID",
                "Run `python -m station.register` to create a station and print its identifier.",
            ),
            station_token=_required(
                env,
                "AMOSCLAUD_STATION_TOKEN",
                "Use the amos_station_... credential shown once at registration.",
            ),
            base_url=_url(env, "AMOSCLAUD_URL", DEFAULT_URL),
            backend_url=_url(env, "AMOSCLAUD_STATION_BACKEND", DEFAULT_BACKEND),
            model=_text(env, "AMOSCLAUD_STATION_MODEL", DEFAULT_MODEL),
            name=_text(env, "AMOSCLAUD_STATION_NAME", default_station_name()),
            capabilities=_list(
                env, "AMOSCLAUD_STATION_CAPABILITIES", (INFERENCE_CAPABILITY,)
            ),
            poll_interval=_number(env, "AMOSCLAUD_STATION_POLL_INTERVAL", 2.0, 0.05, 60.0),
            poll_max_interval=_number(
                env, "AMOSCLAUD_STATION_POLL_MAX_INTERVAL", 15.0, 0.05, 300.0
            ),
            heartbeat_interval=_number(
                env, "AMOSCLAUD_STATION_HEARTBEAT_INTERVAL", 30.0, 1.0, 60.0
            ),
            http_timeout=_number(env, "AMOSCLAUD_STATION_HTTP_TIMEOUT", 15.0, 1.0, 120.0),
            probe_timeout=_number(env, "AMOSCLAUD_STATION_PROBE_TIMEOUT", 10.0, 1.0, 120.0),
            inference_timeout=_number(
                env, "AMOSCLAUD_STATION_INFERENCE_TIMEOUT", 120.0, 5.0, 900.0
            ),
            log_level=_text(env, "AMOSCLAUD_STATION_LOG_LEVEL", "INFO").upper() or "INFO",
        )
        return config.normalised()

    def normalised(self) -> "StationConfig":
        """Repair combinations that would otherwise starve the platform."""
        changes: dict[str, object] = {}
        if not self.model:
            changes["model"] = DEFAULT_MODEL
        if INFERENCE_CAPABILITY not in self.capabilities:
            changes["capabilities"] = (INFERENCE_CAPABILITY, *self.capabilities)
        if self.poll_max_interval < self.poll_interval:
            changes["poll_max_interval"] = self.poll_interval
        # A station is only eligible while last_seen_at is inside the 90s
        # window, so never allow a cadence that cannot keep the station online.
        safe_heartbeat = _clamp(self.heartbeat_interval, 1.0, ONLINE_WINDOW_SECONDS / 3.0)
        if safe_heartbeat != self.heartbeat_interval:
            changes["heartbeat_interval"] = safe_heartbeat
        return replace(self, **changes) if changes else self

    @property
    def station_url(self) -> str:
        return f"{self.base_url}/api/v1/server-stations/{self.station_id}"

    @property
    def heartbeat_url(self) -> str:
        return f"{self.station_url}/heartbeat"

    @property
    def claim_url(self) -> str:
        return f"{self.base_url}/api/v1/model-network/stations/{self.station_id}/claim"

    def complete_url(self, request_id: str) -> str:
        return (
            f"{self.base_url}/api/v1/model-network/stations/{self.station_id}"
            f"/requests/{request_id}/complete"
        )

    def summary(self) -> dict[str, object]:
        """A log-safe view of the configuration. The token is never included."""
        return {
            "station_id": self.station_id,
            "base_url": self.base_url,
            "backend_url": self.backend_url,
            "model": self.model,
            "capabilities": list(self.capabilities),
            "poll_interval": self.poll_interval,
            "heartbeat_interval": self.heartbeat_interval,
            "inference_timeout": self.inference_timeout,
        }
