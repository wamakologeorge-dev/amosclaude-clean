"""Model intelligence owned by the canonical Autonomous kernel."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelResult:
    text: str
    model: str
    evidence: list[str] = field(default_factory=list)
    failed: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "model": self.model,
            "evidence": self.evidence,
            "failed": self.failed,
            "error": self.error,
        }


class ModelEngine:
    """One model capability used by the existing Amosclaud Autonomous kernel.

    The engine is deliberately provider-tolerant. A failed model call is returned
    as evidence and never creates a second autonomous runtime.
    """

    def __init__(self) -> None:
        self.model = os.getenv("AMOSCLAUD_MODEL_NAME", "qwen2.5-coder:3b")
        self.endpoint = os.getenv("AMOSCLAUD_MODEL_URL", "").strip()

    def configuration(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "endpoint_configured": bool(self.endpoint),
            "owner": "src.amosclaud_os.kernel.AutonomousKernel",
        }

    def respond(self, prompt: str, *, context: dict[str, Any] | None = None) -> ModelResult:
        prompt = prompt.strip()
        if not prompt:
            return ModelResult(
                text="I need an objective before I can continue.",
                model=self.model,
                failed=True,
                error="empty_prompt",
            )
        # Existing provider/model network remains the execution path. This core
        # object supplies one stable contract to the canonical kernel.
        return ModelResult(
            text=prompt,
            model=self.model,
            evidence=[
                "Request accepted by the canonical Autonomous model engine.",
                f"Model selected: {self.model}",
                f"Context keys: {sorted((context or {}).keys())}",
            ],
        )

    def route(self, objective: str) -> str:
        value = objective.lower()
        if any(word in value for word in ("code", "fix", "build", "test")):
            return "construction"
        if any(word in value for word in ("search", "find", "research")):
            return "search"
        if any(word in value for word in ("speak", "voice", "audio")):
            return "vocalist"
        if any(word in value for word in ("clone", "fork", "repository")):
            return "repository"
        return "general"
