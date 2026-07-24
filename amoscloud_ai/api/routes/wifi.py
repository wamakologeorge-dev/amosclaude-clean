"""Administrator-only MikroTik Wi-Fi management endpoints.

The integration uses RouterOS REST over HTTPS. Configure it with Railway
variables documented in docs/WIFI_ACCESS_POINT.md.
"""

import os
import secrets
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

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
