"""Client for the Amosclaud station and model-network endpoints."""

from __future__ import annotations

from typing import Any

from station.config import StationConfig
from station.transport import HttpError, TransportError, request_json


class InferenceRequest:
    """One unit of work claimed from the model network."""

    __slots__ = ("id", "messages", "model", "max_tokens", "temperature", "raw")

    def __init__(self, payload: dict[str, Any]) -> None:
        self.raw = payload
        self.id = str(payload.get("id") or "")
        messages = payload.get("messages")
        self.messages = (
            [message for message in messages if isinstance(message, dict)]
            if isinstance(messages, list)
            else []
        )
        self.model = payload.get("model")
        self.max_tokens = payload.get("max_tokens")
        self.temperature = payload.get("temperature")

    @property
    def prompt_characters(self) -> int:
        return sum(len(str(message.get("content") or "")) for message in self.messages)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<InferenceRequest {self.id} messages={len(self.messages)}>"


class PlatformClient:
    """Thin wrapper over the three token-authenticated station endpoints."""

    def __init__(self, config: StationConfig) -> None:
        self.config = config

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.station_token}"}

    def heartbeat(self, version: str, capabilities: list[str], system: dict[str, Any]) -> Any:
        return request_json(
            self.config.heartbeat_url,
            method="POST",
            payload={"version": version, "capabilities": capabilities, "system": system},
            headers=self._auth(),
            timeout=self.config.http_timeout,
        )

    def claim(self) -> InferenceRequest | None:
        payload = request_json(
            self.config.claim_url,
            method="POST",
            payload={},
            headers=self._auth(),
            timeout=self.config.http_timeout,
        )
        if not isinstance(payload, dict) or not payload.get("id"):
            return None
        return InferenceRequest(payload)

    def complete(
        self,
        request_id: str,
        *,
        status: str,
        reply: str | None = None,
        runtime: str = "station",
        error: str | None = None,
    ) -> Any:
        return request_json(
            self.config.complete_url(request_id),
            method="POST",
            payload={
                "status": status,
                "reply": reply,
                "runtime": runtime[:100],
                "error": error[:500] if error else None,
            },
            headers=self._auth(),
            timeout=self.config.http_timeout,
        )


__all__ = ["PlatformClient", "InferenceRequest", "HttpError", "TransportError"]
