"""First-party Amosclaud model provider with safe routing and bounded fallback."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from amoscloud_ai.config import settings


@dataclass(frozen=True)
class ProviderResult:
    reply: str
    runtime: str
    status: str = "ready"


class ProviderUnavailable(RuntimeError):
    """A safe provider failure that does not expose credentials or private hosts."""


def _enabled(name: str, default: bool = False) -> bool:
    fallback = "true" if default else "false"
    return os.getenv(name, fallback).strip().lower() in {"1", "true", "yes", "on"}


def _external_adapters_enabled() -> bool:
    return _enabled("AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS")


def _model_endpoint() -> str:
    return settings.amosclaud_model_url.strip().rstrip("/")


def _api_endpoint() -> str:
    return settings.amosclaud_api_url.strip().rstrip("/")


def _host(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return (parsed.hostname or "").lower().rstrip(".")


def _same_service_api_blocked() -> bool:
    """Prevent the web provider from recursively calling its own public API."""
    if _enabled("AMOSCLAUD_ALLOW_SELF_API"):
        return False
    api_host = _host(_api_endpoint())
    own_hosts = {
        _host(settings.amosclaud_public_url),
        _host(settings.railway_public_domain),
        "amosclaud.com",
        "www.amosclaud.com",
    }
    own_hosts.discard("")
    return bool(api_host and api_host in own_hosts)


def _model_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = settings.amosclaud_model_token.strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _timeout() -> httpx.Timeout:
    total = max(20.0, min(float(settings.amosclaud_model_timeout), 600.0))
    return httpx.Timeout(
        total,
        connect=min(20.0, total),
        read=total,
        write=min(60.0, total),
        pool=min(20.0, total),
    )


def _post_with_retry(url: str, *, headers: dict[str, str], json: dict) -> httpx.Response:
    attempts = max(1, min(int(os.getenv("AMOSCLAUD_MODEL_RETRIES", "2")), 4))
    last_category = "unavailable"
    for attempt in range(attempts):
        try:
            response = httpx.post(url, headers=headers, json=json, timeout=_timeout())
            if response.status_code == 429 or response.status_code >= 500:
                last_category = f"temporary-http-{response.status_code}"
                if attempt + 1 < attempts:
                    time.sleep(min(2**attempt, 4))
                    continue
            response.raise_for_status()
            return response
        except httpx.TimeoutException:
            last_category = "timeout"
        except (httpx.NetworkError, httpx.RemoteProtocolError):
            last_category = "network"
        except httpx.HTTPStatusError as exc:
            # Authentication and request errors should not be retried or exposed.
            raise ProviderUnavailable(f"http-{exc.response.status_code}") from exc
        if attempt + 1 < attempts:
            time.sleep(min(2**attempt, 4))
    raise ProviderUnavailable(last_category)


def _extract_reply(response: httpx.Response, source: str) -> str:
    try:
        payload = response.json()
        choices = payload.get("choices")
        message = choices[0].get("message") if isinstance(choices, list) and choices else None
        text = message.get("content") if isinstance(message, dict) else None
    except (ValueError, AttributeError, IndexError, TypeError) as exc:
        raise ProviderUnavailable(f"{source}-invalid-json") from exc
    if not isinstance(text, str) or not text.strip():
        raise ProviderUnavailable(f"{source}-empty-response")
    return text.strip()


def _self_hosted_reply(history: list[dict[str, str]], system_prompt: str) -> ProviderResult | None:
    endpoint = _model_endpoint()
    if not endpoint:
        return None
    response = _post_with_retry(
        f"{endpoint}/v1/chat/completions",
        headers=_model_headers(),
        json={
            "model": settings.amosclaud_model,
            "messages": [{"role": "system", "content": system_prompt}, *history],
            "temperature": 0.2,
            "max_tokens": max(128, min(int(os.getenv("AMOSCLAUD_MODEL_MAX_TOKENS", "1200")), 8192)),
        },
    )
    return ProviderResult(reply=_extract_reply(response, "self-hosted"), runtime="self-hosted")


def _amosclaud_api_reply(history: list[dict[str, str]], system_prompt: str) -> ProviderResult | None:
    endpoint = _api_endpoint()
    api_key = settings.amosclaud_api_key.strip()
    if not endpoint or not api_key or _same_service_api_blocked():
        return None
    response = _post_with_retry(
        f"{endpoint}/api/v1/provider/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": settings.amosclaud_api_model,
            "messages": [{"role": "system", "content": system_prompt}, *history],
        },
    )
    return ProviderResult(reply=_extract_reply(response, "amosclaud-api"), runtime="amosclaud-api")


def _external_adapter_reply(history: list[dict[str, str]], system_prompt: str) -> ProviderResult | None:
    if not _external_adapters_enabled():
        return None

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
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
            return ProviderResult(reply=text, runtime="anthropic-adapter")

    openai_key = settings.openai_api_key.strip()
    if openai_key:
        response = _post_with_retry(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
            json={
                "model": settings.openai_model,
                "max_tokens": 1200,
                "messages": [{"role": "system", "content": system_prompt}, *history],
            },
        )
        return ProviderResult(reply=_extract_reply(response, "openai"), runtime="openai-adapter")
    return None


def reply(history: list[dict[str, str]], system_prompt: str) -> ProviderResult:
    """Route inference without leaking private endpoint or credential details."""
    from amoscloud_ai.model_network import network_status, request_inference

    failures: list[str] = []
    network = network_status()
    if network.get("ready"):
        try:
            result = request_inference(history, system_prompt)
            text = result.get("reply", "").strip() if isinstance(result, dict) else ""
            if text:
                return ProviderResult(text, f"model-network:{result.get('runtime', 'station')}")
            failures.append("model-network-empty")
        except Exception:
            failures.append("model-network-unavailable")

    # Prefer owned runtimes. The customer API is only used when it is genuinely
    # remote; calling the same public web service would create recursion.
    routes = (
        ("self-hosted", _self_hosted_reply),
        ("amosclaud-api", _amosclaud_api_reply),
        ("external-adapter", _external_adapter_reply),
    )
    for label, factory in routes:
        try:
            result = factory(history, system_prompt)
            if result:
                return result
        except ProviderUnavailable as exc:
            failures.append(f"{label}:{exc}")
        except Exception:
            failures.append(f"{label}:unavailable")

    # Keep detailed categories in server logs/call evidence, not in the user reply.
    category = ",".join(failures[-4:]) or "not-configured"
    return ProviderResult(
        reply=(
            "Amosclaud received the task, but no approved model runtime answered. "
            "No model-guided changes were applied. Check provider status and model-service logs."
        ),
        runtime=f"unavailable:{category}",
        status="degraded",
    )


def probe() -> dict[str, object]:
    """Perform a real routed inference before declaring the planning agent ready."""
    result = reply(
        [{"role": "user", "content": "Reply with exactly: AMOSCLAUD_AGENT_READY"}],
        "You are the Amosclaud readiness probe. Follow the exact response instruction.",
    )
    return {
        "ready": result.status == "ready" and "AMOSCLAUD_AGENT_READY" in result.reply,
        "provider": "amosclaud",
        "runtime": result.runtime,
        "model": settings.amosclaud_model,
        "detail": result.reply[:200] if result.status == "ready" else "Configured runtime did not pass inference readiness.",
    }


def status() -> dict[str, object]:
    """Return safe configuration status without exposing keys or endpoint values."""
    from amoscloud_ai.model_network import network_status

    return {
        "provider": "amosclaud",
        "amosclaud_api_configured": bool(_api_endpoint() and settings.amosclaud_api_key.strip()),
        "amosclaud_api_recursion_blocked": _same_service_api_blocked(),
        "self_hosted_configured": bool(_model_endpoint()),
        "external_adapters_enabled": _external_adapters_enabled(),
        "openai_configured": bool(settings.openai_api_key.strip()),
        "model": settings.amosclaud_model,
        "model_network": network_status(),
    }
