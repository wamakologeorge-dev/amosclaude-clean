"""Single cloud-model gateway used by every Amosclaud agent capability."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from .prompts import SYSTEM_PROMPT


@dataclass(frozen=True)
class ModelConfig:
    endpoint: str
    model: str
    api_key: str | None
    timeout_seconds: int = 90


def load_model_config() -> ModelConfig:
    """Load a remote HTTP API configuration; no local model weights are loaded."""
    return ModelConfig(
        endpoint=os.getenv("AMOSCLAUD_MODEL_ENDPOINT", "").strip().rstrip("/"),
        model=os.getenv("AMOSCLAUD_MODEL", "amosclaud-agent"),
        api_key=os.getenv("AMOSCLAUD_MODEL_TOKEN") or os.getenv("AMOSCLAUD_API_KEY") or None,
        timeout_seconds=int(os.getenv("AMOSCLAUD_MODEL_TIMEOUT", "90")),
    )


class AutonomousModelGateway:
    """One HTTP gateway for planning, debugging, review, and repair prompts."""

    def __init__(self, config: ModelConfig | None = None) -> None:
        self.config = config or load_model_config()

    def available(self) -> bool:
        return bool(self.config.endpoint and self.config.model)

    def describe(self) -> dict[str, Any]:
        return {
            "mode": "remote-http-api",
            "loads_local_weights": False,
            "model": self.config.model,
            "endpoint_configured": bool(self.config.endpoint),
            "token_configured": bool(self.config.api_key),
            "timeout_seconds": self.config.timeout_seconds,
        }

    def complete(self, objective: str, evidence: list[str]) -> str:
        if not self.available():
            raise RuntimeError("AMOSCLAUD_MODEL_ENDPOINT is not configured")
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        response = httpx.post(
            f"{self.config.endpoint}/v1/chat/completions",
            headers=headers,
            json={
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Objective: {objective}\nVerified evidence:\n" + "\n".join(evidence)},
                ],
                "temperature": 0.1,
            },
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"]).strip()

    def plan(self, objective: str, evidence: list[str]) -> list[str]:
        """Return a stable plan while keeping all model access behind this gateway."""
        if not self.available():
            raise RuntimeError("Amosclaud cloud model API is not configured")
        return [
            "Understand the objective and success criteria",
            "Inspect repository evidence and dependency impact",
            *( [f"Prioritize the first verified blocker: {evidence[0][:160]}"] if evidence else [] ),
            "Ask the remote model API for a bounded change proposal",
            "Execute only inside the designated workspace and only when authorized",
            "Run focused verification and report exact evidence",
        ]
