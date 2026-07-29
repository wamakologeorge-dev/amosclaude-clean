"""Administrator-only Wi-Fi management and network diagnostics endpoints.

The integration uses RouterOS REST over HTTPS. Configure it with Railway
variables documented in docs/WIFI_ACCESS_POINT.md.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import socket
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from amoscloud_ai import model_network

router = APIRouter(prefix="/admin/wifi", tags=["admin-wifi"])


class WifiSettings(BaseModel):
    ssid: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=8, max_length=63)
    disabled: bool = False


def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    expected = os.getenv("AMOS_ADMIN_KEY")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AMOS_ADMIN_KEY is not configured",
        )
    if not x_admin_key or not secrets.compare_digest(x_admin_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Administrator authentication required",
        )


def routeros_config() -> tuple[str, str, str, bool]:
    base_url = os.getenv("MIKROTIK_BASE_URL", "").rstrip("/")
    username = os.getenv("MIKROTIK_USERNAME", "")
    password = os.getenv("MIKROTIK_PASSWORD", "")
    verify_tls = os.getenv("MIKROTIK_VERIFY_TLS", "true").lower() == "true"
    if not all((base_url, username, password)):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MikroTik connection variables are not configured",
        )
    return base_url, username, password, verify_tls


async def routeros_request(
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
) -> Any:
    base_url, username, password, verify_tls = routeros_config()
    try:
        async with httpx.AsyncClient(
            auth=(username, password),
            verify=verify_tls,
            timeout=10.0,
        ) as client:
            response = await client.request(method, f"{base_url}{path}", json=json)
            response.raise_for_status()
            return response.json() if response.content else None
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"RouterOS returned HTTP {exc.response.status_code}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not connect to the MikroTik access point",
        ) from exc


def _record(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        value = value[0] if value else {}
    return value if isinstance(value, dict) else {}


def _diagnostic_timeout() -> float:
    try:
        return max(
            1.0,
            min(float(os.getenv("AMOSCLAUD_NETWORK_DIAGNOSTIC_TIMEOUT", "5")), 15.0),
        )
    except ValueError:
        return 5.0


def _network_service_health_url() -> str:
    return os.getenv("AMOSCLAUD_NETWORK_SERVICE_HEALTH_URL", "").strip()


def _internet_probe_url() -> str:
    return os.getenv(
        "AMOSCLAUD_NETWORK_INTERNET_PROBE_URL",
        "https://www.amosclaud.com/health",
    ).strip()


def _diagnostic_hostname() -> str:
    explicit = os.getenv("AMOSCLAUD_NETWORK_DIAGNOSTIC_HOST", "").strip()
    if explicit:
        return explicit
    for candidate in (_network_service_health_url(), _internet_probe_url()):
        hostname = urlparse(candidate).hostname
        if hostname:
            return hostname
    return "www.amosclaud.com"


def _check(
    check_id: str,
    label: str,
    state: str,
    detail: str,
    *,
    latency_ms: int | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": check_id,
        "label": label,
        "state": state,
        "detail": detail,
    }
    if latency_ms is not None:
        payload["latency_ms"] = latency_ms
    if evidence:
        payload["evidence"] = evidence
    return payload


async def _resolve_hostname(hostname: str, timeout: float) -> tuple[bool, int, list[str]]:
    started = time.monotonic()
    try:
        results = await asyncio.wait_for(
            asyncio.to_thread(
                socket.getaddrinfo,
                hostname,
                443,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
            ),
            timeout=timeout,
        )
    except (OSError, TimeoutError):
        latency_ms = round((time.monotonic() - started) * 1000)
        return False, latency_ms, []
    addresses = sorted({str(entry[4][0]) for entry in results if entry[4]})[:4]
    latency_ms = round((time.monotonic() - started) * 1000)
    return bool(addresses), latency_ms, addresses


async def _http_probe(url: str, timeout: float) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {
            "configured": False,
            "reachable": False,
            "detail": "health URL is not configured",
        }
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(
                url,
                headers={"User-Agent": "Amosclaud-Network-Diagnostics/1.0"},
            )
        return {
            "configured": True,
            "reachable": response.is_success,
            "status_code": response.status_code,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "detail": "ok" if response.is_success else "non-success response",
        }
    except httpx.HTTPError as exc:
        return {
            "configured": True,
            "reachable": False,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "detail": type(exc).__name__,
        }


async def _access_point_snapshot() -> dict[str, Any]:
    identity_raw, resources_raw = await asyncio.gather(
        routeros_request("GET", "/rest/system/identity"),
        routeros_request("GET", "/rest/system/resource"),
    )
    identity = _record(identity_raw)
    resources = _record(resources_raw)
    return {
        "identity": identity.get("name") or identity.get("identity") or "MikroTik",
        "platform": resources.get("platform") or resources.get("board-name") or "RouterOS",
        "uptime": resources.get("uptime"),
    }


async def _wifi_snapshot() -> dict[str, Any]:
    interface_id = os.getenv("MIKROTIK_WIFI_INTERFACE_ID", "wifi1")
    interface_raw, registrations_raw = await asyncio.gather(
        routeros_request("GET", f"/rest/interface/wifi/{interface_id}"),
        routeros_request("GET", "/rest/interface/wifi/registration-table"),
    )
    interface = _record(interface_raw)
    registrations = registrations_raw if isinstance(registrations_raw, list) else []
    return {
        "interface": interface_id,
        "ssid": (
            interface.get("configuration.ssid")
            or interface.get("ssid")
            or interface.get("name")
        ),
        "channel": (
            interface.get("channel.frequency")
            or interface.get("frequency")
            or interface.get("channel")
        ),
        "disabled": str(interface.get("disabled", "false")).lower() == "true",
        "connected_devices": len(registrations),
    }


@router.get("/status", dependencies=[Depends(require_admin)])
async def wifi_status() -> dict[str, Any]:
    identity = await routeros_request("GET", "/rest/system/identity")
    resources = await routeros_request("GET", "/rest/system/resource")
    return {"online": True, "identity": identity, "resources": resources}


@router.get("/devices", dependencies=[Depends(require_admin)])
async def connected_devices() -> dict[str, Any]:
    registrations = await routeros_request(
        "GET", "/rest/interface/wifi/registration-table"
    )
    return {"devices": registrations or [], "count": len(registrations or [])}


@router.get("/diagnostics", dependencies=[Depends(require_admin)])
async def network_diagnostics() -> dict[str, Any]:
    """Run bounded local, DNS, internet, and Amosclaud network-service checks."""
    checks: list[dict[str, Any]] = []
    timeout = _diagnostic_timeout()
    access_point: dict[str, Any] = {}

    started = time.monotonic()
    try:
        access_point.update(await _access_point_snapshot())
        checks.append(
            _check(
                "local-network",
                "Local Network",
                "passed",
                "The Amosclaud server reached the managed access point.",
                latency_ms=round((time.monotonic() - started) * 1000),
            )
        )
    except HTTPException as exc:
        checks.append(
            _check(
                "local-network",
                "Local Network",
                "failed",
                str(exc.detail),
                latency_ms=round((time.monotonic() - started) * 1000),
            )
        )

    hostname = _diagnostic_hostname()
    resolved, dns_latency, addresses = await _resolve_hostname(hostname, timeout)
    checks.append(
        _check(
            "name-resolution",
            "Name Resolution",
            "passed" if resolved else "failed",
            (
                f"Resolved {hostname}."
                if resolved
                else f"Could not resolve {hostname} through DNS."
            ),
            latency_ms=dns_latency,
            evidence={"hostname": hostname, "addresses": addresses} if resolved else None,
        )
    )

    started = time.monotonic()
    try:
        access_point.update(await _wifi_snapshot())
        checks.append(
            _check(
                "wifi",
                "Wi-Fi",
                "passed" if not access_point.get("disabled") else "failed",
                (
                    "The managed Wi-Fi interface is enabled."
                    if not access_point.get("disabled")
                    else "The managed Wi-Fi interface is disabled."
                ),
                latency_ms=round((time.monotonic() - started) * 1000),
                evidence={
                    "ssid": access_point.get("ssid"),
                    "channel": access_point.get("channel"),
                    "connected_devices": access_point.get("connected_devices", 0),
                },
            )
        )
    except HTTPException as exc:
        checks.append(
            _check(
                "wifi",
                "Wi-Fi",
                "failed",
                str(exc.detail),
                latency_ms=round((time.monotonic() - started) * 1000),
            )
        )

    internet = await _http_probe(_internet_probe_url(), timeout)
    checks.append(
        _check(
            "internet-connectivity",
            "Internet Connectivity",
            "passed" if internet.get("reachable") else "failed",
            (
                "The Amosclaud server reached the configured internet probe."
                if internet.get("reachable")
                else "The configured internet probe could not be reached."
            ),
            latency_ms=internet.get("latency_ms"),
            evidence={"status_code": internet.get("status_code")}
            if internet.get("status_code") is not None
            else None,
        )
    )

    try:
        local_network_service = model_network.network_status()
    except Exception as exc:
        local_network_service = {
            "configured": True,
            "ready": False,
            "detail": type(exc).__name__,
        }
    remote_health_url = _network_service_health_url()
    remote_network_service = (
        await _http_probe(remote_health_url, timeout)
        if remote_health_url
        else {"configured": False, "reachable": None, "detail": "not configured"}
    )
    network_ready = bool(
        local_network_service.get("ready") or remote_network_service.get("reachable")
    )
    network_configured = bool(
        local_network_service.get("configured") or remote_network_service.get("configured")
    )
    network_state = "passed" if network_ready else "failed" if network_configured else "skipped"
    checks.append(
        _check(
            "amosclaud-network-service",
            "Amosclaud Network Service",
            network_state,
            (
                "The Amosclaud network server service is ready."
                if network_ready
                else (
                    "The Amosclaud network server service is configured but unavailable."
                    if network_configured
                    else "Configure the Amosclaud network server service health URL."
                )
            ),
            latency_ms=remote_network_service.get("latency_ms"),
            evidence={
                "local_ready_stations": local_network_service.get("ready_stations", 0),
                "remote_status_code": remote_network_service.get("status_code"),
            },
        )
    )

    failed = sum(check["state"] == "failed" for check in checks)
    skipped = sum(check["state"] == "skipped" for check in checks)
    overall = "failed" if failed else "degraded" if skipped else "passed"
    return {
        "status": overall,
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": sum(check["state"] == "passed" for check in checks),
            "failed": failed,
            "skipped": skipped,
        },
        "access_point": access_point,
        "network_service": {
            "local": local_network_service,
            "remote": remote_network_service,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.put("/network", dependencies=[Depends(require_admin)])
async def update_network(payload: WifiSettings) -> dict[str, Any]:
    interface_id = os.getenv("MIKROTIK_WIFI_INTERFACE_ID", "wifi1")
    security_id = os.getenv("MIKROTIK_WIFI_SECURITY_ID", "default")

    await routeros_request(
        "PATCH",
        f"/rest/interface/wifi/{interface_id}",
        json={"configuration.ssid": payload.ssid, "disabled": str(payload.disabled).lower()},
    )
    await routeros_request(
        "PATCH",
        f"/rest/interface/wifi/security/{security_id}",
        json={"passphrase": payload.password},
    )
    return {"updated": True, "ssid": payload.ssid, "disabled": payload.disabled}
