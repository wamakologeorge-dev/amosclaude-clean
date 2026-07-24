"""Single cloud-model gateway used by every Amosclaud agent capability."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

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


def _enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_model_config() -> ModelConfig:
    """Load one model provider for Autonomous engineering work.

    The Railway bot URL is checked first so a stale Docker-only model hostname
    cannot silently override the service that the operator explicitly connected.
    """

    bot_endpoint = _first_value(
        "AMOSCLAUD_BOT_URL",
        "AMOSCLAUD_BOT_PUBLIC_URL",
    ).rstrip("/")
    endpoint = bot_endpoint or _first_value(
        "AMOSCLAUD_MODEL_ENDPOINT",
        "AMOSCLAUD_MODEL_URL",
    ).rstrip("/")
    provider = "amosclaud-bot" if bot_endpoint else "amosclaud-model"
    completions_path = (
        _first_value("AMOSCLAUD_BOT_COMPLETIONS_PATH")
        if bot_endpoint
        else _first_value("AMOSCLAUD_MODEL_COMPLETIONS_PATH")
    ) or "/v1/chat/completions"
    model = _first_value(
        "AMOSCLAUD_MODEL",
        "AMOSCLAUD_API_MODEL",
    ) or "amosclaud-agent"
    api_key = _first_value(
        "AMOSCLAUD_BOT_TOKEN" if bot_endpoint else "AMOSCLAUD_MODEL_TOKEN",
        "AMOSCLAUD_API_KEY",
        "EXTERNAL_API_KEY",
    ) or None

    if not endpoint:
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

    if not endpoint and _enabled("AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS"):
        openai_key = _first_value("OPENAI_API_KEY")
        anthropic_key = _first_value("ANTHROPIC_API_KEY")
        if openai_key:
            endpoint = _first_value("OPENAI_BASE_URL") or "https://api.openai.com"
            provider = "openai"
            completions_path = "/v1/chat/completions"
            model = _first_value("OPENAI_MODEL") or "gpt-4o-mini"
            api_key = openai_key
        elif anthropic_key:
            endpoint = "https://api.anthropic.com"
            provider = "anthropic"
            completions_path = "/v1/messages"
            model = _first_value("ANTHROPIC_MODEL") or "claude-3-5-sonnet-latest"
            api_key = anthropic_key

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
    """One HTTP gateway for planning, debugging, review, and repair prompts."""

    def __init__(self, config: ModelConfig | None = None) -> None:
        self.config = config or load_model_config()

    def available(self) -> bool:
        return bool(self.config.endpoint and self.config.model)

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

    def connectivity(self, timeout_seconds: float = 2.0) -> dict[str, Any]:
        """Verify that the configured model host resolves and accepts TCP traffic."""

        if not self.available():
            return {
                "configured": False,
                "reachable": False,
                "code": "model_not_configured",
                "detail": (
                    "Set AMOSCLAUD_BOT_URL, AMOSCLAUD_MODEL_URL, "
                    "AMOSCLAUD_MODEL_ENDPOINT, or AMOSCLAUD_API_URL."
                ),
            }

        parsed = urlparse(self.config.endpoint)
        hostname = parsed.hostname
        if not hostname or parsed.scheme not in {"http", "https"}:
            return {
                "configured": True,
                "reachable": False,
                "code": "invalid_model_url",
                "detail": "The configured model URL must be a valid HTTP or HTTPS URL.",
            }
        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        try:
            socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except socket.gaierror:
            detail = "The configured model hostname cannot be resolved from this service."
            if hostname.endswith(".railway.internal"):
                detail += (
                    " Railway private DNS works only when both services are in "
                    "the same project and environment; otherwise use the bot's "
                    "public HTTPS URL."
                )
            return {
                "configured": True,
                "reachable": False,
                "code": "model_dns_failed",
                "detail": detail,
            }

        try:
            with socket.create_connection(
                (hostname, port),
                timeout=max(0.25, float(timeout_seconds)),
            ):
                pass
        except OSError as exc:
            return {
                "configured": True,
                "reachable": False,
                "code": "model_connection_failed",
                "detail": (
                    "The model hostname resolves, but its service port cannot be "
                    f"reached ({type(exc).__name__})."
                ),
            }

        return {
            "configured": True,
            "reachable": True,
            "code": "ready",
            "detail": "The configured model service is reachable.",
        }

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            if self.config.provider == "anthropic":
                headers["x-api-key"] = self.config.api_key
                headers["anthropic-version"] = "2023-06-01"
            else:
                headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def complete(self, objective: str, evidence: list[str]) -> str:
        connection = self.connectivity()
        if not connection["reachable"]:
            raise RuntimeError(str(connection["detail"]))

        user_content = (
            f"Objective: {objective}\nVerified evidence:\n"
            + "\n".join(evidence)
        )
        if self.config.provider == "anthropic":
            payload = {
                "model": self.config.model,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_content}],
                "temperature": 0.1,
                "max_tokens": int(
                    os.getenv("AMOSCLAUD_MODEL_MAX_TOKENS", "4096")
                ),
            }
        else:
            payload = {
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.1,
                "max_tokens": int(
                    os.getenv("AMOSCLAUD_MODEL_MAX_TOKENS", "4096")
                ),
            }

        response = httpx.post(
            f"{self.config.endpoint}{self.config.completions_path}",
            headers=self._headers(),
            json=payload,
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        response_payload = response.json()

        try:
            if self.config.provider == "anthropic":
                content = "".join(
                    str(item.get("text") or "")
                    for item in response_payload.get("content", [])
                    if isinstance(item, dict)
                )
            else:
                content = response_payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Model API returned an invalid chat response") from exc

        answer = str(content).strip()
        if not answer:
            raise RuntimeError("Model API returned an empty response")
        return answer

    def plan(self, objective: str, evidence: list[str]) -> list[str]:
        """Return a stable plan while all model access stays behind this gateway."""

        connection = self.connectivity()
        if not connection["reachable"]:
            raise RuntimeError(str(connection["detail"]))
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
