"""Optional, bounded Railway service health evidence for readiness responses."""
from __future__ import annotations

import os
import time
from urllib.parse import urlparse

import httpx

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _enabled() -> bool:
    return os.getenv("AMOSCLAUD_RAILWAY_HEALTHCHECK_ENABLED", "false").strip().lower() in _TRUE_VALUES


def _health_url() -> str:
    explicit = os.getenv("AMOSCLAUD_RAILWAY_HEALTH_URL", "").strip()
    if explicit:
        return explicit
    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if not domain:
        return ""
    path = os.getenv("AMOSCLAUD_RAILWAY_HEALTH_PATH", "/health").strip() or "/health"
    if not path.startswith("/"):
        path = f"/{path}"
    return f"https://{domain}{path}"


def status() -> dict[str, object]:
    """Probe an explicitly configured Railway public endpoint without exposing it.

    This evidence is intentionally advisory: it never changes process liveness
    and it is disabled unless an operator opts in.
    """
    if not _enabled():
        return {"enabled": False, "reachable": None, "detail": "disabled"}

    url = _health_url()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"enabled": True, "reachable": False, "detail": "health URL is not configured"}

    try:
        timeout = max(1.0, min(float(os.getenv("AMOSCLAUD_RAILWAY_HEALTH_TIMEOUT", "5")), 30.0))
    except ValueError:
        timeout = 5.0
    started = time.monotonic()
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=False)
        latency_ms = round((time.monotonic() - started) * 1000)
        return {
            "enabled": True,
            "reachable": response.is_success,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "detail": "ok" if response.is_success else "non-success response",
        }
    except httpx.HTTPError as exc:
        latency_ms = round((time.monotonic() - started) * 1000)
        return {
            "enabled": True,
            "reachable": False,
            "latency_ms": latency_ms,
            "detail": f"{type(exc).__name__}",
        }
