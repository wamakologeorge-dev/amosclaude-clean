"""Single model gateway used by every Amosclaud agent capability."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModelConfig:
    endpoint: str
    model: str
    api_key: str | None
    timeout_seconds: int = 90


def load_model_config() -> ModelConfig:
    return ModelConfig(
        endpoint=os.getenv("AMOSCLAUD_MODEL_ENDPOINT", "http://127.0.0.1:11434/api/generate"),
        model=os.getenv("AMOSCLAUD_MODEL", "qwen2.5-coder:3b"),
        api_key=os.getenv("AMOSCLAUD_MODEL_TOKEN") or None,
        timeout_seconds=int(os.getenv("AMOSCLAUD_MODEL_TIMEOUT", "90")),
    )


class AutonomousModelGateway:
    """One gateway for planning, debugging, review, and repair prompts."""

    def __init__(self, config: ModelConfig | None = None) -> None:
        self.config = config or load_model_config()

    def available(self) -> bool:
        return bool(self.config.endpoint and self.config.model)

    def describe(self) -> dict[str, Any]:
        return {
            "model": self.config.model,
            "endpoint_configured": bool(self.config.endpoint),
            "token_configured": bool(self.config.api_key),
            "timeout_seconds": self.config.timeout_seconds,
        }

    def plan(self, objective: str, evidence: list[str]) -> list[str]:
        if not self.available():
            raise RuntimeError("Amosclaud model runtime is not configured")
        # Network invocation remains behind this single gateway. The orchestrator may
        # replace this deterministic fallback with the production model adapter.
        steps = [
            "Understand the objective and success criteria",
            "Inspect repository evidence and dependency impact",
            "Select the smallest reversible action",
            "Execute only when authorization permits",
            "Run focused verification and report evidence",
        ]
        if evidence:
            steps.insert(2, f"Prioritize the first verified blocker: {evidence[0][:160]}")
        return steps
