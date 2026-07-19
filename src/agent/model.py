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


def _first_value(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def load_model_config() -> ModelConfig:
    """Load the remote model API configuration without local model weights."""
    endpoint = _first_value(
        "AMOSCLAUD_MODEL_ENDPOINT",
        "AMOSCLAUD_MODEL_URL",
    ).rstrip("/")
    model = _first_value(
        "AMOSCLAUD_MODEL",
        "AMOSCLAUD_API_MODEL",
    ) or "amosclaud-agent"
    api_key = _first_value(
        "AMOSCLAUD_MODEL_TOKEN",
        "AMOSCLAUD_API_KEY",
        "EXTERNAL_API_KEY",
    ) or None
    timeout_raw = _first_value("AMOSCLAUD_MODEL_TIMEOUT") or "90"
    try:
        timeout_seconds = max(1, int(timeout_raw))
    except ValueError as exc:
        raise ValueError("AMOSCLAUD_MODEL_TIMEOUT must be an integer") from exc
    return ModelConfig(
        endpoint=endpoint,
        model=model,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
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
            raise RuntimeError(
                "AMOSCLAUD_MODEL_ENDPOINT or AMOSCLAUD_MODEL_URL is not configured"
            )
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
                    {
                        "role": "user",
                        "content": (
                            f"Objective: {objective}\nVerified evidence:\n"
                            + "\n".join(evidence)
                        ),
                    },
                ],
                "temperature": 0.1,
            },
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Model API returned an invalid chat response") from exc
        answer = str(content).strip()
        if not answer:
            raise RuntimeError("Model API returned an empty response")
        return answer

    def plan(self, objective: str, evidence: list[str]) -> list[str]:
        """Return a stable plan while all model access stays behind this gateway."""
        if not self.available():
            raise RuntimeError("Amosclaud cloud model API is not configured")
        plan = [
            "Understand the objective and success criteria",
            "Inspect repository evidence and dependency impact",
        ]
        if evidence:
            plan.append(f"Prioritize the first verified blocker: {evidence[0][:160]}")
        plan.extend(
            [
                "Ask the remote model API for a bounded change proposal",
                "Execute only inside the designated workspace when authorized",
                "Run focused verification and report exact evidence",
            ]
        )
        return plan
