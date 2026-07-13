"""First-party Amosclaud model provider.

Clients always talk to Amosclaud. A self-hosted Amosclaud model endpoint is the
primary runtime. External model services, when explicitly enabled, are internal
adapters and are never exposed as the client-facing provider identity.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class ProviderResult:
    reply: str
    runtime: str
    status: str = "ready"


def _external_adapters_enabled() -> bool:
    return os.getenv("AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _self_hosted_reply(history: list[dict[str, str]], system_prompt: str) -> ProviderResult | None:
    endpoint = os.getenv("AMOSCLAUD_MODEL_URL", "").strip().rstrip("/")
    if not endpoint:
        return None

    headers = {"Content-Type": "application/json"}
    token = os.getenv("AMOSCLAUD_MODEL_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = httpx.post(
        f"{endpoint}/v1/chat/completions",
        headers=headers,
        json={
            "model": os.getenv("AMOSCLAUD_MODEL", "qwen2.5-coder:3b"),
            "messages": [{"role": "system", "content": system_prompt}] + history,
            "temperature": 0.2,
            "max_tokens": 1200,
        },
        timeout=float(os.getenv("AMOSCLAUD_MODEL_TIMEOUT", "120")),
    )
    response.raise_for_status()
    payload = response.json()
    text = (payload["choices"][0]["message"]["content"] or "").strip()
    if not text:
        raise RuntimeError("Amosclaud model returned an empty response")
    return ProviderResult(reply=text, runtime="self-hosted")


def _external_adapter_reply(history: list[dict[str, str]], system_prompt: str) -> ProviderResult | None:
    if not _external_adapters_enabled():
        return None

    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        import anthropic

        client = anthropic.Anthropic(api_key=anthropic_key)
        response = client.messages.create(
            model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
            max_tokens=1200,
            system=system_prompt,
            messages=history,
        )
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()
        if text:
            return ProviderResult(reply=text, runtime="external-adapter")

    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {openai_key}"},
            json={
                "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                "max_tokens": 1200,
                "messages": [{"role": "system", "content": system_prompt}] + history,
            },
            timeout=60,
        )
        response.raise_for_status()
        text = (response.json()["choices"][0]["message"]["content"] or "").strip()
        if text:
            return ProviderResult(reply=text, runtime="external-adapter")

    return None


def reply(history: list[dict[str, str]], system_prompt: str) -> ProviderResult:
    """Return a response from the first-party Amosclaud provider."""
    try:
        self_hosted = _self_hosted_reply(history, system_prompt)
        if self_hosted:
            return self_hosted
    except Exception:
        if not _external_adapters_enabled():
            raise

    adapted = _external_adapter_reply(history, system_prompt)
    if adapted:
        return adapted

    return ProviderResult(
        reply=(
            "Amosclaud is running, but its model runtime is not connected. "
            "Start the Amosclaud model service and verify AMOSCLAUD_MODEL_URL."
        ),
        runtime="unconfigured",
        status="degraded",
    )


def status() -> dict[str, object]:
    """Return safe provider status without exposing credentials."""
    return {
        "provider": "amosclaud",
        "self_hosted_configured": bool(os.getenv("AMOSCLAUD_MODEL_URL", "").strip()),
        "external_adapters_enabled": _external_adapters_enabled(),
        "model": os.getenv("AMOSCLAUD_MODEL", "qwen2.5-coder:3b"),
    }
