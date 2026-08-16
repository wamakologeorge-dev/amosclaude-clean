"""Model intelligence owned by the canonical Autonomous kernel.

This engine performs real inference against the Amosclaud model station
(an ollama-compatible endpoint). It authenticates with the first-party
Amosclaud model token when present and falls back to an ollama.com API
key, so both credentials work on the platform and in CI.

A failed model call is returned as honest evidence — the engine never
fabricates an answer and never echoes the prompt back as a response.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

_DEFAULT_MODEL = "qwen2.5-coder:1.5b"
_CHAT_SUFFIX = "/api/chat"


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


def _clamp_timeout(raw: str | None, default: float) -> float:
    try:
        value = float(raw) if raw else default
    except ValueError:
        value = default
    return max(5.0, min(value, 115.0))


class ModelEngine:
    """One model capability used by the existing Amosclaud Autonomous kernel.

    The engine is deliberately provider-tolerant. A failed model call is returned
    as evidence and never creates a second autonomous runtime.
    """

    def __init__(self) -> None:
        self.model = (
            os.getenv("AMOSCLAUD_MODEL_NAME", "").strip()
            or os.getenv("AMOSCLAUD_MODEL", "").strip()
            or _DEFAULT_MODEL
        )
        self.endpoint = (
            os.getenv("AMOSCLAUD_MODEL_URL", "").strip() or os.getenv("OLLAMA_BASE_URL", "").strip()
        ).rstrip("/")
        self._amosclaud_token = os.getenv("AMOSCLAUD_MODEL_TOKEN", "").strip()
        self._ollama_key = os.getenv("OLLAMA_API_KEY", "").strip()
        self.timeout = _clamp_timeout(os.getenv("AMOSCLAUD_MODEL_TIMEOUT"), 55.0)

    @property
    def auth_mode(self) -> str:
        if self._amosclaud_token:
            return "amosclaud-token"
        if self._ollama_key:
            return "ollama-api-key"
        return "none"

    def _station_host(self) -> str:
        try:
            return urlsplit(self.endpoint).netloc or self.endpoint
        except ValueError:
            return "invalid-endpoint"

    def configuration(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "endpoint_configured": bool(self.endpoint),
            "auth_mode": self.auth_mode,
            "timeout_seconds": self.timeout,
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
        if not self.endpoint:
            return ModelResult(
                text=(
                    "The Amosclaud model station is not configured. "
                    "Set AMOSCLAUD_MODEL_URL (and AMOSCLAUD_MODEL_TOKEN or "
                    "OLLAMA_API_KEY) so Autonomous can use real inference."
                ),
                model=self.model,
                failed=True,
                error="model_station_not_configured",
            )

        messages: list[dict[str, str]] = []
        system = str((context or {}).get("system") or "").strip()
        if system:
            messages.append({"role": "system", "content": system[:4000]})
        messages.append({"role": "user", "content": prompt[:8000]})

        url = (
            self.endpoint if self.endpoint.endswith(_CHAT_SUFFIX) else self.endpoint + _CHAT_SUFFIX
        )
        payload = json.dumps({"model": self.model, "messages": messages, "stream": False}).encode(
            "utf-8"
        )
        headers = {"Content-Type": "application/json"}
        token = self._amosclaud_token or self._ollama_key
        if token:
            headers["Authorization"] = f"Bearer {token}"

        scheme = urlsplit(url).scheme.lower()
        if scheme not in {"http", "https"}:
            return ModelResult(
                text=(
                    "The Amosclaud model station URL must use http or https "
                    f"(got {scheme or 'no'} scheme). Autonomous refused the call."
                ),
                model=self.model,
                failed=True,
                error="unsupported_url_scheme",
            )

        started = time.monotonic()
        try:
            request = urllib.request.Request(url, data=payload, headers=headers)  # noqa: S310
            with urllib.request.urlopen(  # nosec B310 - scheme is restricted to http/https above
                request, timeout=self.timeout
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return ModelResult(
                text=(
                    "The Amosclaud model station rejected the request "
                    f"(HTTP {exc.code}). Autonomous did not fabricate an answer."
                ),
                model=self.model,
                failed=True,
                error=f"station_http_{exc.code}",
            )
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            return ModelResult(
                text=(
                    "The Amosclaud model station did not answer "
                    f"({type(exc).__name__}). Autonomous did not fabricate an answer."
                ),
                model=self.model,
                failed=True,
                error=f"station_unreachable:{type(exc).__name__}",
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        text = ""
        if isinstance(body, dict):
            message = body.get("message")
            if isinstance(message, dict):
                text = str(message.get("content") or "").strip()
            if not text:
                choices = body.get("choices")
                if isinstance(choices, list) and choices:
                    first = choices[0]
                    if isinstance(first, dict):
                        text = str((first.get("message") or {}).get("content") or "").strip()
        if not text:
            return ModelResult(
                text=(
                    "The Amosclaud model station returned an empty answer. "
                    "Autonomous did not fabricate a response."
                ),
                model=self.model,
                failed=True,
                error="station_empty_response",
            )

        return ModelResult(
            text=text,
            model=str(body.get("model") or self.model),
            evidence=[
                f"Model station: {self._station_host()}",
                f"Model: {self.model}",
                f"Auth: {self.auth_mode}",
                f"Latency: {latency_ms} ms",
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
