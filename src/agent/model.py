"""Single cloud-model gateway used by every Amosclaud agent capability."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from amoscloud_ai import provider as native_provider

from .prompts import SYSTEM_PROMPT


@dataclass(frozen=True)
class ModelConfig:
    endpoint: str
    model: str
    api_key: str | None
    timeout_seconds: int = 90
    provider: str = "amosclaud-model"
    completions_path: str = "/v1/chat/completions"


def _first_value(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def load_model_config() -> ModelConfig:
    """Describe the native route selected by Amosclaud's shared provider policy.

    Selection itself lives in :mod:`amoscloud_ai.provider`, which tries native
    Amosclaud model routes before considering explicitly enabled adapters.
    """
    endpoint = _first_value(
        "AMOSCLAUD_MODEL_ENDPOINT",
        "AMOSCLAUD_MODEL_URL",
        "AMOSCLAUD_BOT_URL",
    ).rstrip("/")
    provider = "amosclaud-model"
    completions_path = (
        _first_value("AMOSCLAUD_MODEL_COMPLETIONS_PATH") or "/v1/chat/completions"
    )
    model = (
        _first_value("AMOSCLAUD_MODEL", "AMOSCLAUD_API_MODEL")
        or "amosclaud-folder-v1"
    )
    api_key = _first_value("AMOSCLAUD_MODEL_TOKEN") or None

    if endpoint == _first_value("AMOSCLAUD_BOT_URL").rstrip("/") and endpoint:
        provider = "amosclaud-bot"
        completions_path = (
            _first_value("AMOSCLAUD_BOT_COMPLETIONS_PATH") or completions_path
        )
        api_key = (
            _first_value("AMOSCLAUD_BOT_TOKEN", "AMOSCLAUD_MODEL_TOKEN") or api_key
        )
    elif not endpoint:
        api_endpoint = _first_value("AMOSCLAUD_API_URL").rstrip("/")
        api_token = _first_value("AMOSCLAUD_API_KEY")
        if api_endpoint and api_token:
            endpoint = api_endpoint
            provider = "amosclaud-api"
            completions_path = (
                _first_value("AMOSCLAUD_API_COMPLETIONS_PATH")
                or "/api/v1/provider/chat/completions"
            )
            api_key = api_token

    timeout_raw = _first_value("AMOSCLAUD_MODEL_TIMEOUT") or "90"
    try:
        timeout_seconds = max(1, int(timeout_raw))
    except ValueError as exc:
        raise ValueError("AMOSCLAUD_MODEL_TIMEOUT must be an integer") from exc

    if completions_path and not completions_path.startswith("/"):
        completions_path = f"/{completions_path}"

    return ModelConfig(
        endpoint=endpoint,
        model=model,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        provider=provider,
        completions_path=completions_path,
    )


class AutonomousModelGateway:
    """Shared-provider gateway for planning, debugging, review, and repair prompts."""

    def __init__(self, config: ModelConfig | None = None) -> None:
        self.config = config or load_model_config()

    def available(self) -> bool:
        return native_provider.is_configured()

    def describe(self) -> dict[str, Any]:
        return {
            "mode": "remote-http-api",
            "loads_local_weights": False,
            "provider": self.config.provider,
            "model": self.config.model,
            "endpoint_configured": bool(self.config.endpoint),
            "completions_path": self.config.completions_path,
            "token_configured": bool(self.config.api_key),
            "timeout_seconds": self.config.timeout_seconds,
        }

    def complete(self, objective: str, evidence: list[str]) -> str:
        """Generate through the shared native-first Amosclaud provider policy."""
        user_content = (
            f"Objective: {objective}\nVerified evidence:\n"
            + "\n".join(evidence)
        )
        result = native_provider.reply(
            [{"role": "user", "content": user_content}],
            SYSTEM_PROMPT,
        )
        if not result.ok:
            raise RuntimeError(
                result.error or "Amosclaud execution model is not configured"
            )
        return result.reply

    def plan(self, objective: str, evidence: list[str]) -> list[str]:
        """Return a stable plan while all model access stays behind this gateway."""
        if not self.available():
            raise RuntimeError("Amosclaud execution model is not configured")
        plan = [
            "Understand the objective and success criteria",
            "Inspect repository evidence and dependency impact",
        ]
        if evidence:
            plan.append(f"Prioritize the first verified blocker: {evidence[0][:160]}")
        plan.extend(
            [
                "Ask the connected model API for a bounded change proposal",
                "Execute only inside the designated workspace when authorized",
                "Run focused verification and report exact evidence",
            ]
        )
        return plan
