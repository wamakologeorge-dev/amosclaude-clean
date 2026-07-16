"""First-party Amosclaud model provider with bounded retry and normalized responses."""
from __future__ import annotations

import os
import time

import httpx

from amoscloud_ai.model_api_response import ModelApiResponse, normalize_model_api_response

# Backward-compatible name used by the engineering agent and existing tests.
ProviderResult = ModelApiResponse


def _external_adapters_enabled() -> bool:
    return os.getenv("AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS", "false").strip().lower() in {"1", "true", "yes", "on"}


def _model_endpoint() -> str:
    return os.getenv("AMOSCLAUD_MODEL_URL", "").strip().rstrip("/")


def _model_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = os.getenv("AMOSCLAUD_MODEL_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _timeout() -> httpx.Timeout:
    total = max(30.0, float(os.getenv("AMOSCLAUD_MODEL_TIMEOUT", "300")))
    return httpx.Timeout(total, connect=min(20.0, total), read=total, write=min(60.0, total), pool=min(20.0, total))


def _post_with_retry(url: str, *, headers: dict[str, str], json: dict) -> httpx.Response:
    attempts = max(1, min(int(os.getenv("AMOSCLAUD_MODEL_RETRIES", "2")), 4))
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = httpx.post(url, headers=headers, json=json, timeout=_timeout())
            response.raise_for_status()
            return response
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(min(2 ** attempt, 4))
    assert last_error is not None
    raise RuntimeError(f"Amosclaud model endpoint did not answer after {attempts} attempt(s): {type(last_error).__name__}: {last_error}") from last_error


def _require_ready(result: ModelApiResponse, label: str) -> ModelApiResponse:
    if not result.ok:
        raise RuntimeError(result.error or f"{label} returned an empty response")
    return result


def _amosclaud_api_reply(history: list[dict[str, str]], system_prompt: str) -> ProviderResult | None:
    endpoint = os.getenv("AMOSCLAUD_API_URL", "").strip().rstrip("/")
    api_key = os.getenv("AMOSCLAUD_API_KEY", "").strip()
    if not endpoint or not api_key:
        return None
    model = os.getenv("AMOSCLAUD_API_MODEL", "amosclaud-agent")
    response = _post_with_retry(
        f"{endpoint}/api/v1/provider/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": [{"role": "system", "content": system_prompt}, *history]},
    )
    return _require_ready(
        normalize_model_api_response(response.json(), runtime="amosclaud-api", provider="amosclaud", model=model),
        "Amosclaud API",
    )


def _self_hosted_reply(history: list[dict[str, str]], system_prompt: str) -> ProviderResult | None:
    endpoint = _model_endpoint()
    if not endpoint:
        return None
    model = os.getenv("AMOSCLAUD_MODEL", "amosclaud-folder-v1")
    response = _post_with_retry(
        f"{endpoint}/v1/chat/completions",
        headers=_model_headers(),
        json={
            "model": model,
            "messages": [{"role": "system", "content": system_prompt}, *history],
            "temperature": 0.2,
            "max_tokens": int(os.getenv("AMOSCLAUD_MODEL_MAX_TOKENS", "1200")),
        },
    )
    return _require_ready(
        normalize_model_api_response(response.json(), runtime="self-hosted", provider="amosclaud", model=model),
        "Amosclaud model",
    )


def probe() -> dict[str, object]:
    from amoscloud_ai.model_network import network_status, request_inference

    model = os.getenv("AMOSCLAUD_MODEL", "amosclaud-folder-v1")
    network = network_status()
    if network.get("ready"):
        result = request_inference(
            [{"role": "user", "content": "Reply with exactly: AMOSCLAUD_AGENT_READY"}],
            "You are the Amosclaud readiness probe. Follow the exact response instruction.",
            timeout=20,
        )
        normalized = normalize_model_api_response(
            result or {}, runtime=f"model-network:{(result or {}).get('runtime', 'station')}", provider="amosclaud", model=model
        )
        if "AMOSCLAUD_AGENT_READY" in normalized.reply:
            return {"ready": True, "provider": "amosclaud", "runtime": normalized.runtime, "model": normalized.model or model, "stations": network.get("ready_stations", 0), "detail": normalized.reply[:200]}
    if not _model_endpoint():
        return {"ready": False, "provider": "amosclaud", "runtime": "unconfigured", "model": model, "detail": "No ready model station and AMOSCLAUD_MODEL_URL is not configured"}
    try:
        result = _self_hosted_reply(
            [{"role": "user", "content": "Reply with exactly: AMOSCLAUD_AGENT_READY"}],
            "You are the local Amosclaud readiness probe. Follow the user's exact response instruction.",
        )
        reply_text = result.reply.strip() if result else ""
        return {"ready": "AMOSCLAUD_AGENT_READY" in reply_text, "provider": "amosclaud", "runtime": result.runtime if result else "unconfigured", "model": result.model if result and result.model else model, "detail": reply_text[:200]}
    except Exception as exc:
        return {"ready": False, "provider": "amosclaud", "runtime": "self-hosted", "model": model, "detail": f"{type(exc).__name__}: {exc}"}


def _external_adapter_reply(history: list[dict[str, str]], system_prompt: str) -> ProviderResult | None:
    if not _external_adapters_enabled():
        return None
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        import anthropic
        model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
        client = anthropic.Anthropic(api_key=anthropic_key)
        response = client.messages.create(model=model, max_tokens=1200, system=system_prompt, messages=history)
        payload = {
            "id": getattr(response, "id", None),
            "model": getattr(response, "model", model),
            "content": [
                {"type": getattr(block, "type", "text"), "text": getattr(block, "text", "")}
                for block in getattr(response, "content", [])
            ],
            "finish_reason": getattr(response, "stop_reason", None),
            "usage": {
                "input_tokens": getattr(getattr(response, "usage", None), "input_tokens", 0),
                "output_tokens": getattr(getattr(response, "usage", None), "output_tokens", 0),
            },
        }
        return _require_ready(
            normalize_model_api_response(payload, runtime="external-adapter:anthropic", provider="anthropic", model=model),
            "Anthropic adapter",
        )
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {openai_key}"},
            json={"model": model, "max_tokens": 1200, "messages": [{"role": "system", "content": system_prompt}, *history]},
            timeout=60,
        )
        response.raise_for_status()
        return _require_ready(
            normalize_model_api_response(response.json(), runtime="external-adapter:openai", provider="openai", model=model),
            "OpenAI adapter",
        )
    return None


def reply(history: list[dict[str, str]], system_prompt: str) -> ProviderResult:
    from amoscloud_ai.model_network import network_status, request_inference

    errors: list[str] = []
    model = os.getenv("AMOSCLAUD_MODEL", "amosclaud-folder-v1")
    network = network_status()
    if network.get("ready"):
        try:
            network_result = request_inference(history, system_prompt)
            if network_result:
                normalized = normalize_model_api_response(
                    network_result,
                    runtime=f"model-network:{network_result.get('runtime', 'station')}",
                    provider="amosclaud",
                    model=model,
                )
                if normalized.ok:
                    return normalized
                errors.append(normalized.error or "model-network returned no reply")
            else:
                errors.append("model-network returned no result")
        except Exception as exc:
            errors.append(f"model-network {type(exc).__name__}: {exc}")

    for factory in (_amosclaud_api_reply, _self_hosted_reply):
        try:
            result = factory(history, system_prompt)
            if result:
                return result
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")

    try:
        adapted = _external_adapter_reply(history, system_prompt)
        if adapted:
            return adapted
    except Exception as exc:
        errors.append(f"external adapter {type(exc).__name__}: {exc}")

    detail = "; ".join(errors)[-500:] if errors else "No model runtime is configured"
    return ProviderResult(
        reply=f"Amosclaud model planning is unavailable. {detail}",
        runtime="unavailable",
        status="degraded",
        provider="amosclaud",
        model=model,
        error=detail,
    )


def status() -> dict[str, object]:
    from amoscloud_ai.model_network import network_status
    return {
        "provider": "amosclaud",
        "response_contract": "model_api_response.v1",
        "amosclaud_api_configured": bool(os.getenv("AMOSCLAUD_API_URL", "").strip() and os.getenv("AMOSCLAUD_API_KEY", "").strip()),
        "self_hosted_configured": bool(_model_endpoint()),
        "external_adapters_enabled": _external_adapters_enabled(),
        "model": os.getenv("AMOSCLAUD_MODEL", "amosclaud-folder-v1"),
        "model_network": network_status(),
    }
