"""Unit tests for the intelligent model-runtime resolution path.

Every test stubs DNS and TCP so no test ever reaches a real network or a
third-party model API.
"""

from __future__ import annotations

import socket

import httpx
import pytest

from amoscloud_ai import model_runtime, provider

MODEL_ENV = (
    "AMOSCLAUD_MODEL_ENDPOINT",
    "AMOSCLAUD_MODEL_URL",
    "AMOSCLAUD_BOT_URL",
    "AMOSCLAUD_MODEL_TOKEN",
    "AMOSCLAUD_BOT_TOKEN",
    "AMOSCLAUD_API_URL",
    "AMOSCLAUD_PROVIDER_API_URL",
    "AMOSCLAUD_API_KEY",
    "AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AMOSCLAUD_NETWORK_OWNER_USER_ID",
)


@pytest.fixture(autouse=True)
def clean_runtime(monkeypatch):
    """Start every test from an unconfigured deployment with an empty cache."""
    for name in MODEL_ENV:
        monkeypatch.delenv(name, raising=False)
    model_runtime.reset_cache()
    yield
    model_runtime.reset_cache()


def _resolver(unresolvable: set[str]):
    def resolve(host: str, port: int):
        if host in unresolvable:
            raise socket.gaierror(-2, "Name or service not known")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, port))]

    return resolve


def _stub_network(monkeypatch, *, unresolvable: set[str] = frozenset()):
    monkeypatch.setattr(model_runtime, "_resolve_host", _resolver(set(unresolvable)))
    monkeypatch.setattr(
        model_runtime, "_tcp_connect", lambda host, port, timeout: None
    )


def _json_response(content: str):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": content}}]}

    return Response()


def _candidate(key: str) -> model_runtime.Candidate:
    return next(
        item for item in model_runtime.resolve_candidates() if item.key == key
    )


def test_dns_failure_is_classified_with_actionable_remediation(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", "https://amosclaud-model.internal:11434")
    _stub_network(monkeypatch, unresolvable={"amosclaud-model.internal"})

    health = model_runtime.candidate_health(_candidate("self-hosted"), force=True)

    assert health.reachable is False
    assert health.diagnosis is not None
    assert health.diagnosis.code == model_runtime.DNS_UNRESOLVED
    assert (
        "hostname 'amosclaud-model.internal' could not be resolved from this "
        "deployment" in health.diagnosis.remediation
    )
    assert "AMOSCLAUD_MODEL_URL must point to a publicly reachable HTTPS" in (
        health.diagnosis.remediation
    )
    assert "Errno" not in health.diagnosis.remediation
    assert health.to_dict()["endpoint"] == "https://amosclaud-model.internal:11434"


def test_raw_errno_from_transport_is_translated_not_echoed(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", "https://amosclaud-model.internal")
    candidate = _candidate("self-hosted")
    error = httpx.ConnectError("[Errno -2] Name or service not known")
    error.__cause__ = socket.gaierror(-2, "Name or service not known")

    diagnosis = model_runtime.classify(error, candidate)

    assert diagnosis.code == model_runtime.DNS_UNRESOLVED
    assert "could not be resolved" in diagnosis.remediation
    assert "AMOSCLAUD_MODEL_URL" in diagnosis.remediation


@pytest.mark.parametrize(
    "error,expected",
    [
        (ConnectionRefusedError(111, "Connection refused"), "connection_refused"),
        (httpx.ReadTimeout("timed out"), "timeout"),
        (socket.gaierror(-2, "Name or service not known"), "dns_unresolved"),
    ],
)
def test_transport_errors_map_to_stable_codes(monkeypatch, error, expected):
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", "https://model.example.com")

    diagnosis = model_runtime.classify(error, _candidate("self-hosted"))

    assert diagnosis.code == expected
    assert diagnosis.code in model_runtime.DIAGNOSTIC_CODES
    assert diagnosis.remediation


def test_http_status_errors_map_to_auth_and_model_codes(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", "https://model.example.com")
    candidate = _candidate("self-hosted")
    request = httpx.Request("POST", "https://model.example.com/v1/chat/completions")

    unauthorized = httpx.HTTPStatusError(
        "401", request=request, response=httpx.Response(401, request=request)
    )
    missing = httpx.HTTPStatusError(
        "404", request=request, response=httpx.Response(404, request=request)
    )

    assert model_runtime.classify(unauthorized, candidate).code == (
        model_runtime.AUTH_REJECTED
    )
    assert model_runtime.classify(missing, candidate).code == (
        model_runtime.MODEL_NOT_FOUND
    )


def test_unreachable_candidate_is_skipped_and_the_next_one_answers(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_API_URL", "https://api.amosclaud.internal")
    monkeypatch.setenv("AMOSCLAUD_API_KEY", "first-party-key")
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", "https://model.amosclaud.internal")
    _stub_network(monkeypatch, unresolvable={"api.amosclaud.internal"})

    calls: list[str] = []

    def fake_post(url, **_kwargs):
        calls.append(url)
        return _json_response("Self-hosted answered.")

    monkeypatch.setattr(provider.httpx, "post", fake_post)

    result = provider.reply([{"role": "user", "content": "hi"}], "System")

    assert result.reply == "Self-hosted answered."
    assert result.runtime == "self-hosted"
    # The unresolvable first-party API was skipped instead of stalling the run.
    assert calls == ["https://model.amosclaud.internal/v1/chat/completions"]


def test_failing_candidate_falls_through_to_the_next_reachable_one(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_API_URL", "https://api.amosclaud.internal")
    monkeypatch.setenv("AMOSCLAUD_API_KEY", "first-party-key")
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", "https://model.amosclaud.internal")
    monkeypatch.setenv("AMOSCLAUD_MODEL_RETRIES", "1")
    _stub_network(monkeypatch)

    calls: list[str] = []

    def fake_post(url, **_kwargs):
        calls.append(url)
        if "api.amosclaud.internal" in url:
            raise httpx.ConnectError("[Errno 111] Connection refused")
        return _json_response("Fallback answered.")

    monkeypatch.setattr(provider.httpx, "post", fake_post)

    result = provider.reply([{"role": "user", "content": "hi"}], "System")

    assert result.reply == "Fallback answered."
    assert [httpx.URL(url).host for url in calls] == [
        "api.amosclaud.internal",
        "model.amosclaud.internal",
    ]


def test_first_party_is_preferred_over_enabled_external_adapters(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", "https://model.amosclaud.internal")
    monkeypatch.setenv("AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    # The first-party endpoint does not even resolve, and the external adapter
    # host does: first-party must still be attempted first.
    _stub_network(monkeypatch, unresolvable={"model.amosclaud.internal"})

    calls: list[str] = []

    def fake_post(url, **_kwargs):
        calls.append(url)
        assert "openai.com" not in url
        return _json_response("First-party answered.")

    monkeypatch.setattr(provider.httpx, "post", fake_post)

    order = model_runtime.plan().to_dict()["attempt_order"]
    result = provider.reply([{"role": "user", "content": "hi"}], "System")

    assert order[0] == "self-hosted"
    assert order[-1].startswith("external-")
    assert result.runtime == "self-hosted"
    assert calls == ["https://model.amosclaud.internal/v1/chat/completions"]


def test_external_adapters_are_ignored_unless_explicitly_enabled(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-be-used")
    _stub_network(monkeypatch)

    def fail_post(url, **_kwargs):  # pragma: no cover - must never run
        raise AssertionError(f"no request may be made, got {url}")

    monkeypatch.setattr(provider.httpx, "post", fail_post)

    report = model_runtime.health_report()

    assert report["attempt_order"] == []
    assert report["external_adapters_enabled"] is False
    adapters = [
        item for item in report["candidates"] if item["kind"] == "external"
    ]
    assert adapters and all(item["configured"] is False for item in adapters)
    assert all(
        "AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS" in item["remediation"]
        for item in adapters
    )

    result = provider.reply([{"role": "user", "content": "hi"}], "System")
    assert result.status == "degraded"
    assert result.runtime == "unconfigured"
    assert "must-not-be-used" not in (result.error or "")


def test_probe_results_are_cached_for_the_configured_ttl(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", "https://model.amosclaud.internal")
    monkeypatch.setenv("AMOSCLAUD_MODEL_PROBE_TTL", "30")
    resolved: list[str] = []

    def resolve(host, port):
        resolved.append(host)
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(model_runtime, "_resolve_host", resolve)
    monkeypatch.setattr(
        model_runtime, "_tcp_connect", lambda host, port, timeout: None
    )

    candidate = _candidate("self-hosted")
    first = model_runtime.candidate_health(candidate)
    second = model_runtime.candidate_health(candidate)

    assert resolved == ["model.amosclaud.internal"]
    assert first.cached is False
    assert second.cached is True
    assert second.diagnosis is not None
    assert second.diagnosis.code == model_runtime.DNS_UNRESOLVED

    model_runtime.reset_cache()
    model_runtime.candidate_health(candidate)
    assert len(resolved) == 2


def test_diagnostics_redact_credentials_and_sanitize_endpoints(monkeypatch):
    monkeypatch.setenv(
        "AMOSCLAUD_MODEL_URL", "https://operator:s3cr3t@model.internal:8443/v1?key=abc"
    )
    monkeypatch.setenv("AMOSCLAUD_MODEL_TOKEN", "super-secret-model-token")
    _stub_network(monkeypatch)
    candidate = _candidate("self-hosted")

    assert candidate.sanitized_endpoint == "https://model.internal:8443"
    assert "s3cr3t" not in candidate.sanitized_endpoint
    assert "key=abc" not in candidate.sanitized_endpoint

    diagnosis = model_runtime.classify(
        RuntimeError(
            "refused for Authorization: Bearer super-secret-model-token at "
            "https://operator:s3cr3t@model.internal:8443/v1"
        ),
        candidate,
    )

    assert "super-secret-model-token" not in diagnosis.detail
    assert "s3cr3t" not in diagnosis.detail
    assert model_runtime.REDACTED in diagnosis.detail
    assert "super-secret-model-token" not in diagnosis.remediation


def test_no_model_available_reports_a_truthful_blocker(monkeypatch):
    _stub_network(monkeypatch)

    result = provider.reply([{"role": "user", "content": "hi"}], "System")

    assert result.status == "degraded"
    assert result.runtime == "unconfigured"
    assert result.ok is False
    assert "model runtime is not connected" in result.reply
    assert model_runtime.UNCONFIGURED in (result.error or "")
    assert "No code changes were made" in result.reply
    assert "Native Amosclaud repository actions remain available" in result.reply
    assert "AMOSCLAUD_MODEL_URL" in result.reply


def test_blocker_names_the_dns_failure_seen_in_production(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", "https://amosclaud-model.internal:11434")
    monkeypatch.setenv("AMOSCLAUD_MODEL", "qwen2.5-coder:3b")
    _stub_network(monkeypatch, unresolvable={"amosclaud-model.internal"})

    def fake_post(url, **_kwargs):
        raise httpx.ConnectError("[Errno -2] Name or service not known")

    monkeypatch.setattr(provider.httpx, "post", fake_post)

    result = provider.reply([{"role": "user", "content": "hi"}], "System")

    assert result.status == "degraded"
    assert model_runtime.DNS_UNRESOLVED in (result.error or "")
    assert "amosclaud-model.internal" in result.reply
    assert "No code changes were made" in result.reply


def test_health_surface_separates_configuration_from_reachability(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", "https://model.internal:11434/v1")
    monkeypatch.setenv("AMOSCLAUD_MODEL_TOKEN", "secret-token-value")
    _stub_network(monkeypatch, unresolvable={"model.internal"})

    report = model_runtime.health_report()
    self_hosted = next(
        item for item in report["candidates"] if item["candidate"] == "self-hosted"
    )

    assert report["configured"] is True
    assert report["reachable"] is False
    assert report["preferred"] is None
    assert report["resolution_order"][:3] == [
        "model-network",
        "amosclaud-api",
        "self-hosted",
    ]
    assert self_hosted["configured"] is True
    assert self_hosted["reachable"] is False
    assert self_hosted["failure_code"] == model_runtime.DNS_UNRESOLVED
    assert self_hosted["endpoint"] == "https://model.internal:11434"
    assert self_hosted["remediation"]
    assert report["blocker"]["code"] == model_runtime.DNS_UNRESOLVED
    assert "secret-token-value" not in str(report)


def test_provider_status_keeps_existing_keys_and_adds_candidate_health(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", "https://model.internal:11434")
    _stub_network(monkeypatch, unresolvable={"model.internal"})

    state = provider.status()

    assert state["provider"] == "amosclaud"
    assert state["self_hosted_configured"] is True
    assert state["external_adapters_enabled"] is False
    assert state["response_contract"] == "model_api_response.v1"
    assert "model_network" in state
    runtime_state = state["model_runtime"]
    assert runtime_state["reachable"] is False
    assert runtime_state["blocker"]["code"] == model_runtime.DNS_UNRESOLVED


def test_probe_reports_the_blocker_without_stalling(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", "https://model.internal:11434")
    _stub_network(monkeypatch, unresolvable={"model.internal"})

    def fail_post(url, **_kwargs):  # pragma: no cover - must never run
        raise AssertionError("an unresolvable candidate must not be probed by HTTP")

    monkeypatch.setattr(provider.httpx, "post", fail_post)

    state = provider.probe()

    assert state["ready"] is False
    assert state["provider"] == "amosclaud"
    assert state["blocker"]["code"] == model_runtime.DNS_UNRESOLVED
    assert model_runtime.DNS_UNRESOLVED in str(state["detail"])
    assert state["model_runtime"]["reachable"] is False


def test_ready_route_downgrades_when_no_candidate_is_reachable(monkeypatch):
    from fastapi.testclient import TestClient

    from amoscloud_ai.main import create_app

    monkeypatch.setenv("AMOSCLAUD_MODEL_URL", "https://model.internal:11434")
    _stub_network(monkeypatch, unresolvable={"model.internal"})

    client = TestClient(create_app())
    body = client.get("/ready").json()

    assert body["status"] == "degraded"
    assert body["provider"]["self_hosted_configured"] is True
    runtime_state = body["provider"]["model_runtime"]
    assert runtime_state["reachable"] is False
    assert runtime_state["blocker"]["code"] == model_runtime.DNS_UNRESOLVED
    assert "AMOSCLAUD_MODEL_URL" in runtime_state["blocker"]["remediation"]


# --------------------------------------------------------------------------
# AMOSCLAUD_API_URL conflation fix: the model endpoint has its own variable.
# --------------------------------------------------------------------------
def test_dedicated_provider_api_url_is_preferred_for_model_endpoint(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_PROVIDER_API_URL", "https://model.example:8443")
    monkeypatch.setenv("AMOSCLAUD_API_URL", "http://www.amosclaud.com/")
    monkeypatch.setenv("AMOSCLAUD_API_KEY", "key")
    candidate = _candidate("amosclaud-api")
    assert candidate.sanitized_endpoint == "https://model.example:8443"
    assert candidate.endpoint_env == "AMOSCLAUD_PROVIDER_API_URL"


def test_legacy_api_url_still_works_as_backward_compatible_fallback(monkeypatch):
    monkeypatch.delenv("AMOSCLAUD_PROVIDER_API_URL", raising=False)
    monkeypatch.setenv("AMOSCLAUD_API_URL", "https://legacy.example:9000")
    monkeypatch.setenv("AMOSCLAUD_API_KEY", "key")
    candidate = _candidate("amosclaud-api")
    assert candidate.sanitized_endpoint == "https://legacy.example:9000"
    assert candidate.endpoint_env == "AMOSCLAUD_API_URL"


def test_provider_uses_dedicated_endpoint_over_platform_url(monkeypatch):
    # The platform base URL must never be treated as the model endpoint when
    # the dedicated variable is present.
    monkeypatch.setenv("AMOSCLAUD_PROVIDER_API_URL", "https://model.example")
    monkeypatch.setenv("AMOSCLAUD_API_URL", "http://www.amosclaud.com/")
    monkeypatch.setenv("AMOSCLAUD_API_KEY", "key")
    assert provider.status()["amosclaud_api_configured"] is True
    candidate = _candidate("amosclaud-api")
    assert "amosclaud.com" not in candidate.sanitized_endpoint
