"""First-party Amosclaud model provider with bounded retry and normalized responses."""
from __future__ import annotations

import os
import time
from typing import Any

import httpx

from amoscloud_ai import model_runtime
from amoscloud_ai.model_api_response import ModelApiResponse, normalize_model_api_response

# Backward-compatible name used by the engineering agent and existing tests.
ProviderResult = ModelApiResponse


PROBE_INSTRUCTION = "Reply with exactly: AMOSCLAUD_AGENT_READY"
PROBE_TOKEN = "AMOSCLAUD_AGENT_READY"


def _external_adapters_enabled() -> bool:
    return model_runtime.external_adapters_enabled()


def _model_endpoint() -> str:
    """Resolve the first-party model endpoint used by every Amosclaud workflow."""
    for name in ("AMOSCLAUD_MODEL_ENDPOINT", "AMOSCLAUD_MODEL_URL", "AMOSCLAUD_BOT_URL"):
        endpoint = os.getenv(name, "").strip().rstrip("/")
        if endpoint:
            return endpoint
    return ""


def _model_completions_path() -> str:
    path = os.getenv("AMOSCLAUD_MODEL_COMPLETIONS_PATH", "").strip()
    if not path and _model_endpoint() == os.getenv("AMOSCLAUD_BOT_URL", "").strip().rstrip("/"):
        path = os.getenv("AMOSCLAUD_BOT_COMPLETIONS_PATH", "").strip()
    return f"/{path.lstrip('/')}" if path else "/v1/chat/completions"


def _model_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = os.getenv("AMOSCLAUD_MODEL_TOKEN", "").strip()
    if not token and _model_endpoint() == os.getenv("AMOSCLAUD_BOT_URL", "").strip().rstrip("/"):
        token = os.getenv("AMOSCLAUD_BOT_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _timeout(connect: float | None = None) -> httpx.Timeout:
    total = max(30.0, float(os.getenv("AMOSCLAUD_MODEL_TIMEOUT", "300")))
    connect_timeout = min(connect or 20.0, total)
    return httpx.Timeout(
        total, connect=connect_timeout, read=total, write=min(60.0, total),
        pool=min(20.0, total),
    )


def _post_with_retry(
    url: str,
    *,
    headers: dict[str, str],
    json: dict,
    attempts: int | None = None,
) -> httpx.Response:
    if attempts is None:
        attempts = int(os.getenv("AMOSCLAUD_MODEL_RETRIES", "2"))
    attempts = max(1, min(attempts, 4))
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
    raise RuntimeError(
        model_runtime.redact(
            f"Amosclaud model endpoint did not answer after {attempts} "
            f"attempt(s): {type(last_error).__name__}"
        )
    ) from last_error


def _require_ready(result: ModelApiResponse, label: str) -> ModelApiResponse:
    if not result.ok:
        raise RuntimeError(result.error or f"{label} returned an empty response")
    return result


def _amosclaud_api_reply(
    history: list[dict[str, str]],
    system_prompt: str,
    *,
    attempts: int | None = None,
) -> ProviderResult | None:
    endpoint = os.getenv("AMOSCLAUD_API_URL", "").strip().rstrip("/")
    api_key = os.getenv("AMOSCLAUD_API_KEY", "").strip()
    if not endpoint or not api_key:
        return None
    model = os.getenv("AMOSCLAUD_API_MODEL", "amosclaud-agent")
    path = os.getenv("AMOSCLAUD_API_COMPLETIONS_PATH", "/api/v1/provider/chat/completions").strip()
    response = _post_with_retry(
        f"{endpoint}/{path.lstrip('/')}",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": [{"role": "system", "content": system_prompt}, *history]},
        attempts=attempts,
    )
    return _require_ready(
        normalize_model_api_response(response.json(), runtime="amosclaud-api", provider="amosclaud", model=model),
        "Amosclaud API",
    )


def _self_hosted_reply(
    history: list[dict[str, str]],
    system_prompt: str,
    *,
    attempts: int | None = None,
) -> ProviderResult | None:
    endpoint = _model_endpoint()
    if not endpoint:
        return None
    model = os.getenv("AMOSCLAUD_MODEL", "amosclaud-folder-v1")
    response = _post_with_retry(
        f"{endpoint}{_model_completions_path()}",
        headers=_model_headers(),
        json={
            "model": model,
            "messages": [{"role": "system", "content": system_prompt}, *history],
            "temperature": 0.2,
            "max_tokens": int(os.getenv("AMOSCLAUD_MODEL_MAX_TOKENS", "1200")),
        },
        attempts=attempts,
    )
    return _require_ready(
        normalize_model_api_response(response.json(), runtime="self-hosted", provider="amosclaud", model=model),
        "Amosclaud model",
    )


def _model_network_reply(
    history: list[dict[str, str]],
    system_prompt: str,
    *,
    timeout: float | None = None,
) -> ProviderResult | None:
    """Ask the outbound model-network stations for one inference."""
    from amoscloud_ai.model_network import request_inference

    model = os.getenv("AMOSCLAUD_MODEL", "amosclaud-folder-v1")
    result = request_inference(history, system_prompt, timeout=timeout)
    if not result:
        return None
    return normalize_model_api_response(
        result,
        runtime=f"model-network:{result.get('runtime', 'station')}",
        provider="amosclaud",
        model=model,
    )


def _network_status() -> dict[str, Any]:
    return model_runtime.network_state()


def _invoke_candidate(
    candidate: model_runtime.Candidate,
    history: list[dict[str, str]],
    system_prompt: str,
    *,
    attempts: int | None = None,
    timeout: float | None = None,
) -> ProviderResult | None:
    """Call exactly one resolved candidate; never fabricate a reply."""
    if candidate.key == "model-network":
        return _model_network_reply(history, system_prompt, timeout=timeout)
    if candidate.key == "amosclaud-api":
        return _amosclaud_api_reply(history, system_prompt, attempts=attempts)
    if candidate.key == "self-hosted":
        return _self_hosted_reply(history, system_prompt, attempts=attempts)
    return _external_adapter_reply(history, system_prompt)


def probe() -> dict[str, object]:
    """Report readiness from the cached resolution path without stalling."""
    model = os.getenv("AMOSCLAUD_MODEL", "amosclaud-folder-v1")
    network = _network_status()
    active = model_runtime.plan(network)
    history = [{"role": "user", "content": PROBE_INSTRUCTION}]
    system_prompt = (
        "You are the Amosclaud readiness probe. Follow the exact response instruction."
    )
    for health in active.order:
        if not health.candidate.first_party or not health.reachable:
            continue
        try:
            result = _invoke_candidate(
                health.candidate, history, system_prompt, attempts=1, timeout=20
            )
        except Exception as exc:
            model_runtime.record_failure(
                health.candidate, model_runtime.classify(exc, health.candidate)
            )
            continue
        reply_text = (result.reply or "").strip() if result else ""
        if result and PROBE_TOKEN in reply_text:
            return {
                "ready": True,
                "provider": "amosclaud",
                "runtime": result.runtime,
                "model": result.model or model,
                "stations": int(network.get("ready_stations") or 0),
                "detail": reply_text[:200],
                "candidate": health.candidate.key,
                "model_runtime": model_runtime.health_report(network),
            }
        model_runtime.record_failure(
            health.candidate,
            model_runtime.diagnose(
                model_runtime.BAD_RESPONSE,
                "the readiness probe did not return AMOSCLAUD_AGENT_READY",
                health.candidate,
            ),
        )
    report = model_runtime.health_report(network)
    diagnosis = model_runtime.blocker(model_runtime.plan(network))
    runtime = next(
        (
            health.candidate.runtime
            for health in active.order
            if health.candidate.first_party and health.candidate.configured
        ),
        "unconfigured",
    )
    return {
        "ready": False,
        "provider": "amosclaud",
        "runtime": (
            "unconfigured" if diagnosis.code == model_runtime.UNCONFIGURED else runtime
        ),
        "model": model,
        "stations": int(network.get("ready_stations") or 0),
        "detail": f"[{diagnosis.code}] {diagnosis.remediation}"[:400],
        "blocker": diagnosis.to_dict(),
        "model_runtime": report,
    }


def is_configured() -> bool:
    """Whether the shared provider policy has a route it may safely attempt."""
    return any(
        candidate.configured and candidate.available is not False
        for candidate in model_runtime.resolve_candidates()
    )


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
    """Answer through the first usable candidate in the resolution path."""
    model = os.getenv("AMOSCLAUD_MODEL", "amosclaud-folder-v1")
    network = _network_status()
    active = model_runtime.plan(network)
    errors: list[str] = []
    adapter_attempted = False
    for health in active.order:
        candidate = health.candidate
        if not candidate.first_party:
            if adapter_attempted:
                continue
            adapter_attempted = True
        # A candidate the preflight already reported unreachable still gets one
        # bounded attempt, but never a long retry loop.
        attempts = None if health.reachable else 1
        try:
            result = _invoke_candidate(
                candidate, history, system_prompt, attempts=attempts
            )
        except Exception as exc:
            diagnosis = model_runtime.record_failure(
                candidate, model_runtime.classify(exc, candidate)
            )
            errors.append(f"{candidate.label}: [{diagnosis.code}] {diagnosis.detail}")
            continue
        if result is None:
            errors.append(
                f"{candidate.label}: [{model_runtime.UNCONFIGURED}] no usable route"
            )
            continue
        if result.ok:
            return result
        diagnosis = model_runtime.record_failure(
            candidate,
            model_runtime.diagnose(
                model_runtime.BAD_RESPONSE,
                result.error or "the model returned an empty reply",
                candidate,
            ),
        )
        errors.append(f"{candidate.label}: [{diagnosis.code}] {diagnosis.detail}")

    diagnosis = model_runtime.blocker(model_runtime.plan(network))
    detail = "; ".join(errors)[-500:] if errors else diagnosis.detail
    return ProviderResult(
        reply=model_runtime.blocker_message(diagnosis),
        runtime="unconfigured",
        status="degraded",
        provider="amosclaud",
        model=model,
        error=model_runtime.redact(f"[{diagnosis.code}] {detail}"),
    )


def status() -> dict[str, object]:
    from src.agent.model import load_model_config

    selection = load_model_config()
    network = _network_status()
    return {
        "provider": "amosclaud",
        "response_contract": "model_api_response.v1",
        "amosclaud_api_configured": bool(os.getenv("AMOSCLAUD_API_URL", "").strip() and os.getenv("AMOSCLAUD_API_KEY", "").strip()),
        "self_hosted_configured": bool(_model_endpoint()),
        "external_adapters_enabled": _external_adapters_enabled(),
        "openai_configured": bool(os.getenv("OPENAI_API_KEY", "").strip()),
        "anthropic_configured": bool(os.getenv("ANTHROPIC_API_KEY", "").strip()),
        "model": os.getenv("AMOSCLAUD_MODEL", "amosclaud-folder-v1"),
        "autonomous_selection": {
            "provider": selection.provider,
            "model": selection.model,
            "configured": bool(selection.endpoint),
            "external": selection.provider in {"openai", "anthropic"},
        },
        "model_network": network,
        "model_runtime": model_runtime.health_report(network),
    }
