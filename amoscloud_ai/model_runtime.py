"""Intelligent model-runtime resolution, preflight, and diagnostics.

The provider layer used to try a single endpoint and, when its hostname did
not resolve, surfaced the raw operating-system error (for example
``[Errno -2] Name or service not known``) to the browser and stopped.

This module owns one ordered resolution path, a cheap cached preflight, and
stable machine diagnostic codes with human remediation text, so every caller
can degrade gracefully and explain a model outage truthfully:

1. ``model-network`` stations, when the network reports ready stations
2. the first-party Amosclaud API endpoint
3. the self-hosted ``AMOSCLAUD_MODEL_URL`` endpoint
4. external adapters, only when ``AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS`` is
   explicitly enabled *and* an adapter key is configured

First-party candidates are always attempted before external adapters, and no
module here ever invents or simulates model output.
"""

from __future__ import annotations

import os
import re
import socket
import ssl
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urlsplit

import httpx

# Stable machine codes. Callers may switch on these; do not rename them.
DNS_UNRESOLVED = "dns_unresolved"
CONNECTION_REFUSED = "connection_refused"
TLS_ERROR = "tls_error"
TIMEOUT = "timeout"
AUTH_REJECTED = "auth_rejected"
MODEL_NOT_FOUND = "model_not_found"
BAD_RESPONSE = "bad_response"
UNCONFIGURED = "unconfigured"

DIAGNOSTIC_CODES: tuple[str, ...] = (
    DNS_UNRESOLVED,
    CONNECTION_REFUSED,
    TLS_ERROR,
    TIMEOUT,
    AUTH_REJECTED,
    MODEL_NOT_FOUND,
    BAD_RESPONSE,
    UNCONFIGURED,
)

_TRUE_VALUES = {"1", "true", "yes", "on"}
_SELF_HOSTED_ENV_NAMES = (
    "AMOSCLAUD_MODEL_ENDPOINT",
    "AMOSCLAUD_MODEL_URL",
    "AMOSCLAUD_BOT_URL",
)
# The remote-hosted first-party ``amosclaud-api`` model endpoint.
#
# Historically this candidate read ``AMOSCLAUD_API_URL``, but that variable is
# already the Amosclaud *platform* base URL everywhere else (``shared.runtime``
# and ``deployment_worker.config`` both treat it as the platform API, live
# value ``http://www.amosclaud.com/``). Treating the platform URL as a model
# API endpoint is a conflation bug: a preflight would probe the website as if
# it were an inference server. ``AMOSCLAUD_PROVIDER_API_URL`` is the dedicated
# model-endpoint variable; ``AMOSCLAUD_API_URL`` is kept only as a
# backward-compatible fallback so existing deployments do not break.
_FIRST_PARTY_API_ENV_NAMES = (
    "AMOSCLAUD_PROVIDER_API_URL",
    "AMOSCLAUD_API_URL",
)
_SECRET_ENV_NAMES = (
    "AMOSCLAUD_MODEL_TOKEN",
    "AMOSCLAUD_BOT_TOKEN",
    "AMOSCLAUD_API_KEY",
    "AMOSCLAUD_MASTER_KEY",
    "AMOSCLAUD_OWNER_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
)
_SECRET_PATTERNS = (
    re.compile(r"://[^/@\s]+@"),
    re.compile(r"(?i)\b(bearer)\s+[^\s\"']+"),
    re.compile(
        r"(?i)\b(api[-_]?key|token|secret|password|authorization)"
        r"\s*[:=]\s*[^\s,;\"']+"
    ),
    re.compile(r"(?i)\b(sk|ak|ghp|gho|xoxb)[-_][A-Za-z0-9._\-]{8,}"),
)
REDACTED = "***redacted***"


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in _TRUE_VALUES


def _env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def external_adapters_enabled() -> bool:
    """Whether the operator explicitly opted in to external model adapters."""
    return _flag("AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS")


def redact(text: str) -> str:
    """Remove credentials from any text that may reach a user or a log."""
    cleaned = str(text)
    for name in _SECRET_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if len(value) >= 4:
            cleaned = cleaned.replace(value, REDACTED)
    cleaned = _SECRET_PATTERNS[0].sub(f"://{REDACTED}@", cleaned)
    cleaned = _SECRET_PATTERNS[1].sub(rf"\1 {REDACTED}", cleaned)
    cleaned = _SECRET_PATTERNS[2].sub(rf"\1={REDACTED}", cleaned)
    cleaned = _SECRET_PATTERNS[3].sub(REDACTED, cleaned)
    return cleaned


def sanitize_endpoint(endpoint: str) -> str:
    """Return ``scheme://host[:port]`` only: never userinfo, path, or query."""
    raw = (endpoint or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw if "//" in raw else f"//{raw}", scheme="https")
    try:
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        return REDACTED
    if not host:
        return REDACTED
    scheme = parts.scheme or "https"
    return f"{scheme}://{host}:{port}" if port else f"{scheme}://{host}"


def endpoint_host_port(endpoint: str) -> tuple[str, int]:
    """Split an endpoint into a hostname and the port a probe should use."""
    parts = urlsplit(endpoint if "//" in endpoint else f"//{endpoint}", scheme="https")
    try:
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        return "", 0
    if port:
        return host, port
    return host, 80 if parts.scheme == "http" else 443


@dataclass(frozen=True)
class Candidate:
    """One resolvable way to reach a model runtime, in priority order."""

    key: str
    label: str
    runtime: str
    kind: str
    endpoint: str = ""
    endpoint_env: str = ""
    token_env: str = ""
    configured: bool = False
    requires_endpoint: bool = True
    available: bool | None = None
    note: str = ""

    @property
    def first_party(self) -> bool:
        return self.kind != "external"

    @property
    def sanitized_endpoint(self) -> str:
        return sanitize_endpoint(self.endpoint)

    @property
    def host(self) -> str:
        return endpoint_host_port(self.endpoint)[0] if self.endpoint else ""


@dataclass(frozen=True)
class Diagnosis:
    """A stable machine code plus safe, actionable human text."""

    code: str
    detail: str
    remediation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "detail": self.detail,
            "remediation": self.remediation,
        }


@dataclass(frozen=True)
class CandidateHealth:
    """Cheap, cached preflight verdict for one candidate."""

    candidate: Candidate
    reachable: bool
    diagnosis: Diagnosis | None = None
    checked_at: float = 0.0
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "candidate": self.candidate.key,
            "label": self.candidate.label,
            "kind": self.candidate.kind,
            "configured": self.candidate.configured,
            "reachable": self.reachable,
            "endpoint": self.candidate.sanitized_endpoint,
            "endpoint_env": self.candidate.endpoint_env,
            "failure_code": self.diagnosis.code if self.diagnosis else None,
            "remediation": self.diagnosis.remediation if self.diagnosis else "",
            "detail": self.diagnosis.detail if self.diagnosis else "",
            "cached": self.cached,
        }
        return payload


_REMEDIATION_HINTS = {
    DNS_UNRESOLVED: (
        "Amosclaud model endpoint hostname '{host}' could not be resolved from "
        "this deployment — {endpoint_env} must point to a publicly reachable "
        "HTTPS endpoint or a private hostname inside the same network."
    ),
    CONNECTION_REFUSED: (
        "Nothing is accepting connections at {endpoint} — start the Amosclaud "
        "model service and confirm {endpoint_env} carries the port the "
        "inference server binds."
    ),
    TLS_ERROR: (
        "TLS could not be negotiated with {endpoint} — give {endpoint_env} a "
        "certificate that this deployment trusts, or use plain http only "
        "inside a private network."
    ),
    TIMEOUT: (
        "{endpoint} accepted work but did not answer in time — check model "
        "service load, raise AMOSCLAUD_MODEL_TIMEOUT, and confirm "
        "{endpoint_env} points at the inference port."
    ),
    AUTH_REJECTED: (
        "{endpoint} rejected the Amosclaud credentials — correct or rotate "
        "{token_env}; its value is never logged or echoed."
    ),
    MODEL_NOT_FOUND: (
        "{endpoint} does not serve the requested model — install or pull the "
        "model on the model host, or correct AMOSCLAUD_MODEL."
    ),
    BAD_RESPONSE: (
        "{endpoint} answered with a payload Amosclaud cannot use — confirm "
        "{endpoint_env} points at an OpenAI-compatible chat completions "
        "service."
    ),
    UNCONFIGURED: (
        "No model runtime is configured for this candidate — set "
        "{endpoint_env} to a first-party Amosclaud model endpoint. No "
        "external API key is required."
    ),
}


# ``unconfigured`` means something different for a station pool, a
# first-party endpoint, and an opt-in adapter, so each gets its own hint.
_UNCONFIGURED_HINTS = {
    "network": (
        "No Amosclaud model station is available — connect a station and set "
        "{endpoint_env} to the owning user id, or configure a first-party "
        "model endpoint instead."
    ),
    "external": (
        "This adapter is inactive by design — Amosclaud uses it only when "
        "AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS is enabled and {endpoint_env} is "
        "set. First-party routes are always preferred and no external API "
        "key is required."
    ),
}


def remediation(code: str, candidate: Candidate) -> str:
    """Human remediation text naming the environment variable to correct."""
    template = _REMEDIATION_HINTS.get(code, _REMEDIATION_HINTS[BAD_RESPONSE])
    if code == UNCONFIGURED:
        template = _UNCONFIGURED_HINTS.get(candidate.kind, template)
    endpoint = candidate.sanitized_endpoint or "the configured model endpoint"
    return template.format(
        host=candidate.host or "(unset)",
        endpoint=endpoint,
        endpoint_env=candidate.endpoint_env or "AMOSCLAUD_MODEL_URL",
        token_env=candidate.token_env or "AMOSCLAUD_MODEL_TOKEN",
    )


def diagnose(code: str, detail: str, candidate: Candidate) -> Diagnosis:
    return Diagnosis(
        code=code,
        detail=redact(detail)[:300],
        remediation=remediation(code, candidate),
    )


def _status_code(error: BaseException) -> int | None:
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


_DNS_MARKERS = (
    "name or service not known",
    "name resolution",
    "nodename nor servname",
    "no address associated",
)


def _code_for_message(text: str) -> str | None:
    lowered = text.lower()
    if any(marker in lowered for marker in _DNS_MARKERS):
        return DNS_UNRESOLVED
    if "certificate" in lowered or "ssl" in lowered:
        return TLS_ERROR
    if "refused" in lowered:
        return CONNECTION_REFUSED
    if "timed out" in lowered or "timeout" in lowered:
        return TIMEOUT
    return None


def _code_for_error(error: BaseException) -> str | None:
    if isinstance(error, (socket.gaierror, socket.herror)):
        return DNS_UNRESOLVED
    if isinstance(error, ssl.SSLError):
        return TLS_ERROR
    if isinstance(error, ConnectionRefusedError):
        return CONNECTION_REFUSED
    if isinstance(error, (socket.timeout, TimeoutError, httpx.TimeoutException)):
        return TIMEOUT
    if isinstance(error, httpx.HTTPStatusError):
        status = _status_code(error)
        if status in {401, 403, 407}:
            return AUTH_REJECTED
        if status in {404, 409}:
            return MODEL_NOT_FOUND
        return BAD_RESPONSE
    code = _code_for_message(str(error))
    if code:
        return code
    return CONNECTION_REFUSED if isinstance(error, httpx.ConnectError) else None


def classify(error: BaseException, candidate: Candidate) -> Diagnosis:
    """Translate any transport or protocol error into a stable diagnosis."""
    seen: set[int] = set()
    current: BaseException | None = error
    code: str | None = None
    while current is not None and id(current) not in seen and len(seen) < 8:
        seen.add(id(current))
        code = _code_for_error(current)
        if code:
            break
        current = current.__cause__ or current.__context__
    detail = f"{type(error).__name__}: {error}"
    return diagnose(code or BAD_RESPONSE, detail, candidate)


def network_state() -> dict[str, Any]:
    """Read the model-network state without ever raising into a caller."""
    from amoscloud_ai.model_network import network_status

    try:
        state = network_status()
    except Exception as error:  # pragma: no cover - defensive
        return {"configured": False, "ready": False, "detail": redact(str(error))}
    return dict(state) if isinstance(state, dict) else {}


def resolve_candidates(network: dict[str, Any] | None = None) -> list[Candidate]:
    """Return every model candidate in the single ordered resolution path."""
    network = network_state() if network is None else dict(network)
    stations = int(network.get("ready_stations") or 0)
    network_ready = bool(network.get("ready"))
    api_endpoint = _env(*_FIRST_PARTY_API_ENV_NAMES).rstrip("/")
    api_endpoint_env = "AMOSCLAUD_PROVIDER_API_URL"
    for name in _FIRST_PARTY_API_ENV_NAMES:
        if os.getenv(name, "").strip():
            api_endpoint_env = name
            break
    api_key = _env("AMOSCLAUD_API_KEY")
    self_hosted = _env(*_SELF_HOSTED_ENV_NAMES).rstrip("/")
    self_hosted_env = "AMOSCLAUD_MODEL_URL"
    for name in _SELF_HOSTED_ENV_NAMES:
        if os.getenv(name, "").strip():
            self_hosted_env = name
            break
    candidates = [
        Candidate(
            key="model-network",
            label="Amosclaud model network stations",
            runtime="model-network",
            kind="network",
            endpoint_env="AMOSCLAUD_NETWORK_OWNER_USER_ID",
            configured=bool(network.get("configured")),
            requires_endpoint=False,
            available=network_ready,
            note=str(network.get("detail") or f"{stations} ready station(s)"),
        ),
        Candidate(
            key="amosclaud-api",
            label="First-party Amosclaud API",
            runtime="amosclaud-api",
            kind="first-party",
            endpoint=api_endpoint,
            endpoint_env=api_endpoint_env,
            token_env="AMOSCLAUD_API_KEY",
            configured=bool(api_endpoint and api_key),
        ),
        Candidate(
            key="self-hosted",
            label="Self-hosted Amosclaud model",
            runtime="self-hosted",
            kind="first-party",
            endpoint=self_hosted,
            endpoint_env=self_hosted_env,
            token_env="AMOSCLAUD_MODEL_TOKEN",
            configured=bool(self_hosted),
        ),
    ]
    if network_ready:
        candidates[0] = replace(candidates[0], configured=True)
    adapters_enabled = external_adapters_enabled()
    for key, env_name, label in (
        ("external-anthropic", "ANTHROPIC_API_KEY", "Anthropic adapter"),
        ("external-openai", "OPENAI_API_KEY", "OpenAI adapter"),
    ):
        configured = adapters_enabled and bool(_env(env_name))
        candidates.append(
            Candidate(
                key=key,
                label=label,
                runtime=f"external-adapter:{key.removeprefix('external-')}",
                kind="external",
                endpoint_env=env_name,
                token_env=env_name,
                configured=configured,
                requires_endpoint=False,
                available=configured,
                note=(
                    "opt-in adapter"
                    if adapters_enabled
                    else "AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS is not enabled"
                ),
            )
        )
    return candidates


def probe_ttl_seconds() -> float:
    try:
        return max(0.0, float(os.getenv("AMOSCLAUD_MODEL_PROBE_TTL", "30")))
    except ValueError:
        return 30.0


def connect_budget_seconds() -> float:
    try:
        budget = float(os.getenv("AMOSCLAUD_MODEL_PROBE_TIMEOUT", "2"))
    except ValueError:
        return 2.0
    return max(0.2, min(budget, 10.0))


_CACHE: dict[str, CandidateHealth] = {}
_CACHE_LOCK = threading.Lock()


def reset_cache() -> None:
    """Forget every cached preflight verdict (used by tests and operators)."""
    with _CACHE_LOCK:
        _CACHE.clear()


def _cache_key(candidate: Candidate) -> str:
    return f"{candidate.key}|{candidate.sanitized_endpoint}"


def _cached(candidate: Candidate) -> CandidateHealth | None:
    ttl = probe_ttl_seconds()
    if ttl <= 0:
        return None
    with _CACHE_LOCK:
        entry = _CACHE.get(_cache_key(candidate))
    if entry is None or time.monotonic() - entry.checked_at > ttl:
        return None
    return CandidateHealth(
        candidate=candidate,
        reachable=entry.reachable,
        diagnosis=entry.diagnosis,
        checked_at=entry.checked_at,
        cached=True,
    )


def _store(health: CandidateHealth) -> CandidateHealth:
    with _CACHE_LOCK:
        _CACHE[_cache_key(health.candidate)] = health
    return health


def _resolve_host(host: str, port: int) -> list[Any]:
    """Resolve a hostname. Split out so tests can stub DNS without sockets."""
    return socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)


def _tcp_connect(host: str, port: int, timeout: float) -> None:
    """Open and immediately close a short TCP probe connection."""
    socket.create_connection((host, port), timeout=timeout).close()


def _preflight(candidate: Candidate) -> CandidateHealth:
    now = time.monotonic()
    if not candidate.configured:
        return CandidateHealth(
            candidate=candidate,
            reachable=False,
            diagnosis=diagnose(
                UNCONFIGURED, candidate.note or "not configured", candidate
            ),
            checked_at=now,
        )
    if not candidate.requires_endpoint:
        available = True if candidate.available is None else candidate.available
        if available:
            return CandidateHealth(candidate=candidate, reachable=True, checked_at=now)
        return CandidateHealth(
            candidate=candidate,
            reachable=False,
            diagnosis=diagnose(
                UNCONFIGURED, candidate.note or "no runtime is available", candidate
            ),
            checked_at=now,
        )
    host, port = endpoint_host_port(candidate.endpoint)
    if not host:
        return CandidateHealth(
            candidate=candidate,
            reachable=False,
            diagnosis=diagnose(
                BAD_RESPONSE, "the configured endpoint has no hostname", candidate
            ),
            checked_at=now,
        )
    try:
        _resolve_host(host, port)
    except Exception as error:
        return CandidateHealth(
            candidate=candidate,
            reachable=False,
            diagnosis=classify(error, candidate),
            checked_at=now,
        )
    try:
        _tcp_connect(host, port, connect_budget_seconds())
    except Exception as error:
        return CandidateHealth(
            candidate=candidate,
            reachable=False,
            diagnosis=classify(error, candidate),
            checked_at=now,
        )
    return CandidateHealth(candidate=candidate, reachable=True, checked_at=now)


def candidate_health(candidate: Candidate, *, force: bool = False) -> CandidateHealth:
    """Return a cached-or-fresh preflight verdict for one candidate."""
    if not force:
        cached = _cached(candidate)
        if cached is not None:
            return cached
    return _store(_preflight(candidate))


def record_failure(candidate: Candidate, diagnosis: Diagnosis) -> Diagnosis:
    """Remember a real request failure so repeated calls fail fast."""
    _store(
        CandidateHealth(
            candidate=candidate,
            reachable=False,
            diagnosis=diagnosis,
            checked_at=time.monotonic(),
        )
    )
    return diagnosis


@dataclass(frozen=True)
class AttemptPlan:
    """Ordered attempt plan: healthy first-party, deferred, then adapters."""

    healths: tuple[CandidateHealth, ...] = field(default=())

    @property
    def order(self) -> tuple[CandidateHealth, ...]:
        first_party = [item for item in self.healths if item.candidate.first_party]
        external = [item for item in self.healths if not item.candidate.first_party]
        usable = [item for item in first_party if item.reachable]
        deferred = [
            item
            for item in first_party
            if not item.reachable and item.candidate.configured
        ]
        adapters = [item for item in external if item.candidate.configured]
        return tuple([*usable, *deferred, *adapters])

    @property
    def configured(self) -> tuple[CandidateHealth, ...]:
        return tuple(item for item in self.healths if item.candidate.configured)

    def to_dict(self) -> dict[str, Any]:
        return {
            "resolution_order": [item.candidate.key for item in self.healths],
            "attempt_order": [item.candidate.key for item in self.order],
            "candidates": [item.to_dict() for item in self.healths],
        }


def plan(network: dict[str, Any] | None = None) -> AttemptPlan:
    """Build the ordered attempt plan using cached preflight results."""
    return AttemptPlan(
        tuple(
            candidate_health(candidate)
            for candidate in resolve_candidates(network)
        )
    )


def blocker(current: AttemptPlan | None = None) -> Diagnosis:
    """Explain, truthfully, why no model candidate can currently serve work."""
    active = current or plan()
    for item in active.order:
        if item.diagnosis is not None:
            return item.diagnosis
    unconfigured = Candidate(
        key="self-hosted",
        label="Self-hosted Amosclaud model",
        runtime="unconfigured",
        kind="first-party",
        endpoint_env="AMOSCLAUD_MODEL_URL",
        token_env="AMOSCLAUD_MODEL_TOKEN",
    )
    return diagnose(
        UNCONFIGURED,
        "no model candidate is configured for this deployment",
        unconfigured,
    )


def blocker_message(diagnosis: Diagnosis) -> str:
    """Truthful agent-facing text for a model outage; never invents output."""
    return (
        "Amosclaud model runtime is not connected, so no model reply was "
        f"produced. Blocker [{diagnosis.code}]: {diagnosis.remediation} "
        "No code changes were made and no model output was simulated. "
        "Native Amosclaud repository actions remain available: create, read, "
        "and write repositories, run tests, and open pull requests."
    )


def health_report(network: dict[str, Any] | None = None) -> dict[str, Any]:
    """Bounded configuration-versus-reachability surface for /ready and status."""
    active = plan(network)
    usable = [item for item in active.order if item.reachable]
    report = active.to_dict()
    report.update(
        {
            "configured": bool(active.configured),
            "reachable": bool(usable),
            "preferred": usable[0].candidate.key if usable else None,
            "probe_ttl_seconds": probe_ttl_seconds(),
            "external_adapters_enabled": external_adapters_enabled(),
        }
    )
    if not usable:
        report["blocker"] = blocker(active).to_dict()
    return report
